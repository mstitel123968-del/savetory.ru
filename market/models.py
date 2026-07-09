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

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        SCHEDULED = "scheduled", "Ожидает начала"
        ACTIVE = "active", "Аукцион идёт"
        COMPLETED = "completed", "Завершён"
        CANCELLED = "cancelled", "Отменён"

    class Condition(models.TextChoices):
        NEW = "new", "Новый"
        EXCELLENT = "excellent", "Отличное"
        GOOD = "good", "Хорошее"
        SATISFACTORY = "satisfactory", "Удовлетворительное"
        RESTORATION = "restoration", "Требует восстановления"

    class DeliveryMethod(models.TextChoices):
        DELIVERY = "delivery", "Доставка"
        PICKUP = "pickup", "Самовывоз"
        MEETING = "meeting", "Личная встреча"
        AGREEMENT = "agreement", "По договорённости"

    class StartMode(models.TextChoices):
        NOW = "now", "Начать сразу"
        SCHEDULED = "scheduled", "Запланировать"

    class AuctionResult(models.TextChoices):
        NO_BIDS = "no_bids", "Без ставок"
        RESERVE_NOT_REACHED = "reserve_not_reached", "Резерв не достигнут"
        SOLD = "sold", "Продано"
        CANCELLED = "cancelled", "Отменён"

    # Statuses that mean the listing is published/live vs. not.
    LIVE_STATUSES = (Status.SCHEDULED, Status.ACTIVE)
    INACTIVE_STATUSES = (Status.DRAFT, Status.COMPLETED, Status.CANCELLED)
    AUTO_EXTEND_MIN_MINUTES = 1
    AUTO_EXTEND_MAX_MINUTES = 30

    item = models.ForeignKey("core.ArchiveFile", on_delete=models.CASCADE, related_name="listings")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listings")
    type = models.CharField(max_length=16, choices=Type.choices)
    # Blank is permitted so an auction draft can be saved before the seller
    # picks a category; clean() still requires it for every non-draft listing.
    category = models.CharField(max_length=32, choices=Category.choices, blank=True, db_index=True)

    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    # Legacy publication flag kept for backwards compatibility with current
    # pages/API until a dedicated refactor. Synchronised with ``status``.
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    swap_wishlist = models.TextField(blank=True)

    # Item presentation / handover details.
    item_condition = models.CharField(max_length=16, choices=Condition.choices, blank=True, default="")
    location = models.CharField(max_length=255, blank=True, default="")
    delivery_methods = models.JSONField(default=list, blank=True)
    delivery_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    delivery_note = models.TextField(blank=True, default="")

    auction_start = models.DateTimeField(null=True, blank=True)
    auction_end = models.DateTimeField(null=True, blank=True)
    auction_start_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Renamed from auction_min_price (reserve price). See auction_min_price
    # compatibility property below.
    auction_reserve_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    auction_step = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    current_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    auction_auto_extend = models.BooleanField(default=True)
    auction_auto_extend_minutes = models.PositiveIntegerField(default=2)
    # Draft-time start choice: "now" vs a scheduled start. Lets a draft remember
    # the seller's intent and duration without fixing a start date prematurely.
    auction_start_mode = models.CharField(max_length=16, choices=StartMode.choices, default=StartMode.NOW)
    auction_duration_minutes = models.PositiveIntegerField(null=True, blank=True)

    # --- Auction outcome / cancellation (set once at finalization) ----------
    auction_result = models.CharField(max_length=24, choices=AuctionResult.choices, blank=True, default="")
    winner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="won_auctions")
    winning_bid = models.ForeignKey("AuctionBid", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, default="")
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="cancelled_auctions")
    is_admin_cancelled = models.BooleanField(default=False)

    # --- Administrative moderation (set from the hidden editor page) ---------
    # "Недействителен": excluded from public/active listings and from bidding.
    is_invalidated = models.BooleanField(default=False, db_index=True)
    # "Снят с публикации": kept but not shown publicly.
    is_unpublished = models.BooleanField(default=False, db_index=True)
    moderation_reason = models.TextField(blank=True, default="")
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="moderated_listings")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return self.title or f"{self.get_type_display()} · {self.item.title}"

    # Backwards-compatible alias for the renamed reserve price so existing
    # callers (market API, auction services, archive.js payloads, tests) keep
    # working without changes.
    @property
    def auction_min_price(self):
        return self.auction_reserve_price

    @auction_min_price.setter
    def auction_min_price(self, value):
        self.auction_reserve_price = value

    def _sync_status_and_active(self) -> None:
        """Keep ``status`` and the legacy ``is_active`` flag consistent.

        ``is_active`` is treated as authoritative because current callers only
        set it; a contradicting status is coerced to the matching side. Richer
        statuses (scheduled/completed/cancelled) are preserved when they already
        agree with ``is_active``.
        """
        if self.is_active:
            if self.status not in self.LIVE_STATUSES:
                self.status = self.Status.ACTIVE
        else:
            if self.status not in self.INACTIVE_STATUSES:
                self.status = self.Status.DRAFT

    def _validate_delivery(self, errors: dict) -> None:
        methods = self.delivery_methods
        if methods in (None, ""):
            methods = []
            self.delivery_methods = methods
        if not isinstance(methods, list):
            errors["delivery_methods"] = "Ожидается список способов передачи."
            return
        seen: set[str] = set()
        for method in methods:
            if method not in self.DeliveryMethod.values:
                errors["delivery_methods"] = "Недопустимый способ передачи."
                break
            if method in seen:
                errors["delivery_methods"] = "Способы передачи не должны повторяться."
                break
            seen.add(method)
        if self.delivery_cost is not None:
            if self.delivery_cost < 0:
                errors["delivery_cost"] = "Стоимость доставки не может быть отрицательной."
            if self.DeliveryMethod.DELIVERY not in methods:
                errors["delivery_cost"] = "Стоимость доставки допустима только при выбранной доставке."

    def _validate_auction(self, errors: dict) -> None:
        requires_full = self.status in self.LIVE_STATUSES

        if requires_full:
            if self.auction_start is None:
                errors["auction_start"] = "Укажите дату начала аукциона."
            if self.auction_end is None:
                errors["auction_end"] = "Укажите дату окончания аукциона."
            for field_name in ("auction_start_price", "auction_step"):
                if getattr(self, field_name) is None:
                    errors[field_name] = "Поле обязательно."

        # Value checks apply whenever a value is present (also for drafts).
        if self.auction_start_price is not None and self.auction_start_price <= 0:
            errors["auction_start_price"] = "Стартовая цена должна быть положительной."
        if self.auction_step is not None and self.auction_step <= 0:
            errors["auction_step"] = "Шаг ставки должен быть положительным."
        if self.auction_start and self.auction_end and self.auction_end <= self.auction_start:
            errors["auction_end"] = "Окончание должно быть позже начала."
        if self.auction_reserve_price is not None:
            if self.auction_reserve_price < 0:
                errors["auction_reserve_price"] = "Резервная цена не может быть отрицательной."
            elif self.auction_start_price is not None and self.auction_reserve_price < self.auction_start_price:
                errors["auction_reserve_price"] = "Резервная цена не может быть ниже стартовой."

        minutes = self.auction_auto_extend_minutes
        if minutes is None or not (self.AUTO_EXTEND_MIN_MINUTES <= minutes <= self.AUTO_EXTEND_MAX_MINUTES):
            errors["auction_auto_extend_minutes"] = (
                f"Автопродление должно быть от {self.AUTO_EXTEND_MIN_MINUTES} "
                f"до {self.AUTO_EXTEND_MAX_MINUTES} минут."
            )

        if self.current_price is None and self.auction_start_price is not None:
            self.current_price = self.auction_start_price

    def clean(self) -> None:
        self._sync_status_and_active()
        errors: dict[str, str] = {}

        if not self.item_id:
            errors["item"] = "Не выбран файл архива."
        if not self.seller_id:
            errors["seller"] = "Не выбран продавец."
        if not self.type:
            errors["type"] = "Укажите тип объявления."
        if not self.category:
            # An auction draft may be saved without a category yet.
            if not (self.type == self.Type.AUCTION and self.status == self.Status.DRAFT):
                errors["category"] = "Выберите рубрику."
        elif self.category not in self.Category.values:
            errors["category"] = "Некорректная рубрика."

        # Delivery / handover validation applies to every listing type.
        self._validate_delivery(errors)

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
            self._validate_auction(errors)
            if self.status in self.LIVE_STATUSES and self.seller_id:
                try:
                    from core.services.subscriptions import assert_can_create_active_auction

                    assert_can_create_active_auction(self.seller, exclude_listing_id=self.pk)
                except ValidationError as exc:
                    errors["subscription"] = exc.messages[0]
        else:
            # For other types ensure auction-specific fields are reset
            self.auction_start = None
            self.auction_end = None
            self.auction_start_price = None
            self.auction_reserve_price = None
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
        """Return the minimal allowed bid increment for auction listings."""
        if self.type != self.Type.AUCTION:
            return None
        if self.auction_step is None:
            return None
        return self.auction_step


class ListingImage(models.Model):
    """A lot's own image, optionally derived from an archive card image.

    Lot images and their order are independent of the source archive card:
    editing or deleting a ``ListingImage`` never touches ``ArchiveFileImage``
    (the optional ``source_image`` link uses SET_NULL).
    """

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="images")
    source_image = models.ForeignKey(
        "core.ArchiveFileImage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    image = models.ImageField(upload_to="listing_images/", blank=True, null=True)
    display_order = models.PositiveIntegerField(default=0)
    is_cover = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "id"]
        constraints = [
            # The same archive image cannot be added to one lot twice.
            models.UniqueConstraint(
                fields=["listing", "source_image"],
                condition=models.Q(source_image__isnull=False),
                name="uniq_listing_source_image",
            ),
            # At most one cover per lot.
            models.UniqueConstraint(
                fields=["listing"],
                condition=models.Q(is_cover=True),
                name="uniq_listing_cover",
            ),
            models.CheckConstraint(
                check=models.Q(display_order__gte=0),
                name="listing_image_order_nonneg",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Изображение лота {self.listing_id} (#{self.display_order})"

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.display_order is not None and self.display_order < 0:
            errors["display_order"] = "Порядок не может быть отрицательным."
        if self.is_cover and self.listing_id:
            other_covers = ListingImage.objects.filter(listing_id=self.listing_id, is_cover=True)
            if self.pk:
                other_covers = other_covers.exclude(pk=self.pk)
            if other_covers.exists():
                errors["is_cover"] = "У лота уже есть обложка."
        if self.source_image_id and self.listing_id:
            duplicates = ListingImage.objects.filter(
                listing_id=self.listing_id, source_image_id=self.source_image_id
            )
            if self.pk:
                duplicates = duplicates.exclude(pk=self.pk)
            if duplicates.exists():
                errors["source_image"] = "Это изображение уже добавлено в лот."
        if errors:
            raise ValidationError(errors)


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
            min_amount = listing.auction_step
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


class AuctionBid(models.Model):
    """A bid on a published auction lot.

    Records are immutable after creation (the only post-create change is the
    ``is_winning`` flag, applied via ``queryset.update()``); there is no public
    delete path. The auction start price is never stored as a bid.
    """

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="auction_bids")
    bidder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="auction_bids")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    previous_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_winning = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["listing"], name="auctionbid_listing_idx"),
            models.Index(fields=["bidder"], name="auctionbid_bidder_idx"),
            models.Index(fields=["created_at"], name="auctionbid_created_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"AuctionBid {self.amount} on listing {self.listing_id}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("AuctionBid is immutable after creation.")
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
