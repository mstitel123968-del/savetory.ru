"""Auction domain models for the «Аукцион» section.

Per the chosen architecture, :class:`market.Listing` is the base advertisement
entity (seller, card, publication, category, URL). :class:`AuctionLot` is a
**one-to-one extension** of an auction-typed ``Listing`` that holds only the
auction-specific parameters — pricing, bidding step, the bidding window, the
current price, the winner and anti-sniping extension settings — plus an
immutable snapshot of the card so an active or finished auction never changes
when the source archive card is later edited or deleted.

Bids are stored on the existing :class:`market.Bid` model — this app does not
introduce a parallel bidding flow.

Payment and delivery are intentionally *not* implemented here.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AuctionLot(models.Model):
    """Auction-specific extension of a ``market.Listing`` (type=auction)."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        SCHEDULED = 'scheduled', 'Торги запланированы'
        ACTIVE = 'active', 'Участвует в торгах'
        SOLD = 'sold', 'Продано'
        ENDED = 'ended', 'Торги завершены'
        CANCELLED = 'cancelled', 'Отменено'

    # Statuses in which buyers can already see the lot, so the frozen snapshot
    # must no longer follow edits to the source card.
    LOCKED_STATUSES = frozenset({
        Status.ACTIVE,
        Status.SOLD,
        Status.ENDED,
        Status.CANCELLED,
    })
    # Statuses from which the seller may put the item up for auction again.
    RELISTABLE_STATUSES = frozenset({Status.CANCELLED, Status.ENDED})

    listing = models.OneToOneField(
        'market.Listing',
        on_delete=models.CASCADE,
        related_name='auction_lot',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    # --- Pricing & bidding -----------------------------------------------------
    start_price = models.DecimalField(max_digits=12, decimal_places=2)
    current_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Цена моментальной покупки — необязательно.
    buy_now_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    min_bid_step = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1.00'))

    # --- Bidding window --------------------------------------------------------
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)

    # --- Anti-sniping extension settings ("продление") -------------------------
    auto_extend = models.BooleanField(default=False)
    extend_seconds = models.PositiveIntegerField(default=0)

    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='won_auction_lots',
        null=True,
        blank=True,
    )

    # --- Frozen card snapshot (set at publication) -----------------------------
    snapshot = models.JSONField(default=dict, blank=True)
    snapshot_images = models.JSONField(default=list, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'end_at'], name='auction_status_end_idx'),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Лот #{self.pk} ({self.get_status_display()})"

    # -- Convenience accessors --------------------------------------------------
    @property
    def card(self):
        """The source archive card, via the base listing."""
        return self.listing.item if self.listing_id else None

    @property
    def author(self):
        """The seller, via the base listing."""
        return self.listing.seller if self.listing_id else None

    # -- Lifecycle helpers ------------------------------------------------------
    def is_snapshot_locked(self) -> bool:
        return self.status in self.LOCKED_STATUSES

    def can_relist(self) -> bool:
        return self.status in self.RELISTABLE_STATUSES

    def get_minimum_bid_amount(self) -> Decimal:
        base = self.current_price if self.current_price is not None else self.start_price
        return base + self.min_bid_step

    def build_card_snapshot(self) -> tuple[dict, list]:
        """Copy the displayed card data and photos for freezing."""
        card = self.card
        if card is None:
            return {}, []
        data = {
            'card_id': card.pk,
            'title': card.title,
            'status': card.status,
            'rubric': card.rubric.name if card.rubric_id else '',
            'data': card.data,
        }
        images = [
            {'url': image.image.url if image.image else '', 'display_order': image.display_order}
            for image in card.images.all()
        ]
        return data, images

    def capture_snapshot(self) -> None:
        """Freeze the card data/photos onto the lot. Call when publishing."""
        self.snapshot, self.snapshot_images = self.build_card_snapshot()
        self.published_at = timezone.now()

    # -- Validation -------------------------------------------------------------
    def clean(self) -> None:
        errors: dict[str, str] = {}

        if self.start_price is not None and self.start_price <= 0:
            errors['start_price'] = 'Стартовая цена должна быть положительной.'
        if self.min_bid_step is not None and self.min_bid_step <= 0:
            errors['min_bid_step'] = 'Шаг ставки должен быть положительным.'
        if self.buy_now_price is not None:
            if self.buy_now_price <= 0:
                errors['buy_now_price'] = 'Цена моментальной покупки должна быть положительной.'
            elif self.start_price is not None and self.buy_now_price < self.start_price:
                errors['buy_now_price'] = 'Цена моментальной покупки не может быть ниже стартовой.'
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            errors['end_at'] = 'Завершение должно быть позже начала.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        if self.current_price is None and self.start_price is not None:
            self.current_price = self.start_price
        super().save(*args, **kwargs)
