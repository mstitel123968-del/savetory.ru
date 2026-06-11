"""Translates the Java listing, bidding and messaging entities into Django ORM models."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Listing(models.Model):
    class Type(models.TextChoices):
        SHOP = "shop", "Магазин"
        AUCTION = "auction", "Аукцион"
        FREE = "free", "Даром"
        WANTED = "wanted", "Спрос"
        SWAP = "swap", "Обмен"

    class Category(models.TextChoices):
        COLLECTING = "collecting", "Коллекционирование"
        AUTO = "auto", "Авто"
        REALTY = "realty", "Недвижимость"
        JOBS = "jobs", "Работа"
        ELECTRONICS = "electronics", "Электроника"
        HOME = "home", "Для дома и дачи"
        FASHION = "fashion", "Одежда, обувь, аксессуары"
        HOBBY = "hobby", "Хобби и отдых"
        SERVICES = "services", "Услуги"

    item = models.ForeignKey("core.ArchiveFile", on_delete=models.CASCADE, related_name="listings")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listings")
    type = models.CharField(max_length=16, choices=Type.choices)
    category = models.CharField(max_length=32, choices=Category.choices, db_index=True)

    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    swap_wishlist = models.TextField(blank=True)

    auction_start = models.DateTimeField(null=True, blank=True)
    auction_end = models.DateTimeField(null=True, blank=True)
    auction_start_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    auction_min_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    auction_step = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    current_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return self.title or f"{self.get_type_display()} · {self.item.title}"

    def clean(self) -> None:
        errors: dict[str, str] = {}

        if not self.item_id:
            errors["item"] = "Не выбран файл архива."
        if not self.seller_id:
            errors["seller"] = "Не выбран продавец."
        if not self.type:
            errors["type"] = "Укажите тип объявления."
        if not self.category:
            errors["category"] = "Выберите рубрику."
        elif self.category not in self.Category.values:
            errors["category"] = "Некорректная рубрика."

        if self.type in {self.Type.SHOP, self.Type.WANTED}:
            if self.price is None:
                errors["price"] = "Укажите цену."
            elif self.price <= 0:
                errors["price"] = "Цена должна быть положительной."
        elif self.type == self.Type.FREE:
            if self.price not in (None, Decimal("0")):
                errors["price"] = "Для объявлений «Даром» цена не указывается."
            self.price = None
        elif self.type == self.Type.SWAP:
            wishlist = (self.swap_wishlist or "").strip()
            self.swap_wishlist = wishlist
            if not wishlist:
                errors["swap_wishlist"] = "Опишите варианты обмена."
        elif self.type == self.Type.AUCTION:
            if self.auction_start is None:
                errors["auction_start"] = "Укажите дату начала аукциона."
            if self.auction_end is None:
                errors["auction_end"] = "Укажите дату окончания аукциона."
            if self.auction_start and self.auction_end and self.auction_end <= self.auction_start:
                errors["auction_end"] = "Окончание должно быть позже начала."
            for field_name in (
                "auction_start_price",
                "auction_min_price",
                "auction_step",
            ):
                value = getattr(self, field_name)
                if value is None:
                    errors[field_name] = "Поле обязательно."
                elif value <= 0:
                    errors[field_name] = "Значение должно быть положительным."
            if self.auction_start_price is not None and self.auction_min_price is not None:
                if self.auction_min_price < self.auction_start_price:
                    errors["auction_min_price"] = "Минимальная цена не может быть ниже стартовой."
            if not errors.get("auction_step") and self.auction_step is not None:
                # nothing extra, placeholder for future checks
                pass
            if self.current_price is None and self.auction_start_price is not None:
                self.current_price = self.auction_start_price
        else:
            # For other types ensure auction-specific fields are reset
            self.auction_start = None
            self.auction_end = None
            self.auction_start_price = None
            self.auction_min_price = None
            self.auction_step = None
            self.current_price = None
            self.swap_wishlist = self.swap_wishlist if self.type == self.Type.SWAP else ""

        if self.type not in {self.Type.SHOP, self.Type.WANTED}:
            # optional but ensure price cleared unless type requires
            if self.type != self.Type.AUCTION:
                self.price = None

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def get_minimum_bid_amount(self) -> Decimal | None:
        """Return the minimal allowed bid for auction listings."""
        if self.type != self.Type.AUCTION:
            return None
        base = self.current_price or self.auction_start_price
        if base is None or self.auction_step is None:
            return None
        return base + self.auction_step


class Bid(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="bids")
    bidder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bids")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Ставка {self.amount} для {self.listing_id}"

    def clean(self) -> None:
        errors: dict[str, str] = {}
        listing = self.listing
        if listing is None or listing.type != Listing.Type.AUCTION:
            errors["listing"] = "Ставки доступны только для аукционов."
        else:
            now = timezone.now()
            if listing.auction_start and now < listing.auction_start:
                errors["amount"] = "Аукцион ещё не начался."
            if listing.auction_end and now >= listing.auction_end:
                errors["amount"] = "Аукцион завершён."
            if listing.seller_id == self.bidder_id:
                errors["amount"] = "Нельзя делать ставки на собственный лот."
            min_amount = None
            if listing.current_price is not None and listing.auction_step is not None:
                min_amount = listing.current_price + listing.auction_step
            elif listing.auction_start_price is not None and listing.auction_step is not None:
                min_amount = listing.auction_start_price + listing.auction_step
            if min_amount is not None and self.amount is not None:
                if self.amount < min_amount:
                    errors["amount"] = "Ставка ниже минимального шага."
        if self.amount is None or self.amount <= 0:
            errors["amount"] = errors.get("amount") or "Укажите положительную сумму."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Message(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="messages", null=True, blank=True)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="received_messages")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Сообщение от {self.sender_id} к {self.recipient_id}"
