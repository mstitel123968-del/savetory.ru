"""Business logic bridging the «Аукцион» section with «Ваш архив».

These helpers are the single backend entry point for the integration so views
(and tests) never have to reassemble the rules:

* the per-user system «Аукцион» rubric is created lazily and exactly once;
* publishing a card creates a ``market.Listing`` (the base ad) plus a
  :class:`auction.AuctionLot` extension and freezes a card snapshot;
* the source card always stays in place — it is never copied;
* a card with a live lot cannot be deleted;
* selling writes the final price/status back onto the card without exposing the
  winner's identity to other users.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.models import ArchiveFile, Profile, Rubric
from core.services.subscriptions import assert_can_create_archive_file

from .constants import AUCTION_FIELD_SCHEMA, AUCTION_RUBRIC_NAME, AUCTION_RUBRIC_SLUG
from .models import AuctionLot

# A lot is "live" (and its card therefore protected) while it is scheduled or
# actively running.
ACTIVE_LOCK_STATUSES = (AuctionLot.Status.SCHEDULED, AuctionLot.Status.ACTIVE)


class AuctionError(ValidationError):
    """Raised for auction-integration rule violations (carries a message)."""


# --- System rubric ------------------------------------------------------------
def get_or_create_auction_rubric(user) -> Rubric:
    """Return the user's system «Аукцион» rubric, creating it once if needed.

    Idempotent: repeated calls never create duplicates. The rubric is flagged
    ``is_system`` and carries the fixed, immutable field schema.
    """
    profile, _ = Profile.objects.get_or_create(user=user)
    rubric, created = Rubric.objects.get_or_create(
        profile=profile,
        slug=AUCTION_RUBRIC_SLUG,
        defaults={
            'name': AUCTION_RUBRIC_NAME,
            'is_system': True,
            'is_text_mode': False,
            'field_schema': AUCTION_FIELD_SCHEMA,
        },
    )
    if not created and not rubric.is_system:
        # Heal a pre-existing rubric that collided on the reserved slug.
        rubric.is_system = True
        rubric.name = AUCTION_RUBRIC_NAME
        rubric.field_schema = AUCTION_FIELD_SCHEMA
        rubric.save(update_fields=['is_system', 'name', 'field_schema', 'updated_at'])
    return rubric


def is_auction_rubric(rubric: Rubric) -> bool:
    return bool(rubric) and rubric.is_system and rubric.slug == AUCTION_RUBRIC_SLUG


# --- Lot lookup & deletion guard ---------------------------------------------
def lots_for_card(card: ArchiveFile):
    """All auction lots ever created for a card, newest first."""
    return AuctionLot.objects.filter(listing__item=card).order_by('-created_at')


def latest_lot_for_card(card: ArchiveFile) -> AuctionLot | None:
    return lots_for_card(card).select_related('listing', 'winner').first()


def card_active_lot(card: ArchiveFile) -> AuctionLot | None:
    """Return a scheduled/active lot for the card, or ``None``.

    Used for the *deletion* guard — a draft does not block deletion.
    """
    return AuctionLot.objects.filter(
        listing__item=card, status__in=ACTIVE_LOCK_STATUSES
    ).first()


# A lot is "unfinished" while it is a draft, scheduled, or active. A card with
# an unfinished lot must not receive a second one — the existing lot is opened
# (drafts) or shown (scheduled/active) instead.
UNFINISHED_STATUSES = (AuctionLot.Status.DRAFT,) + ACTIVE_LOCK_STATUSES


def card_blocking_lot(card: ArchiveFile) -> AuctionLot | None:
    """Return the card's unfinished lot (draft/scheduled/active), or ``None``.

    This is per-card and status-driven, so finished lots (sold/ended/cancelled)
    never block re-listing and other cards are never affected.
    """
    return (
        AuctionLot.objects.filter(listing__item=card, status__in=UNFINISHED_STATUSES)
        .select_related('listing')
        .order_by('-created_at')
        .first()
    )


def assert_card_deletable(card: ArchiveFile) -> None:
    """Raise :class:`AuctionError` if the card has a live lot (req. 11)."""
    lot = card_active_lot(card)
    if lot is not None:
        raise AuctionError(
            'Нельзя удалить карточку: товар участвует в активных торгах '
            f'(лот #{lot.pk}). Завершите или отмените лот, затем повторите.'
        )


# --- Publishing a card to auction --------------------------------------------
def _import_listing_model():
    # Local import to keep the dependency direction explicit and avoid any
    # import-time coupling between the apps.
    from market.models import Listing

    return Listing


def _compute_status(start_at, end_at) -> str:
    now = timezone.now()
    if start_at and now < start_at:
        return AuctionLot.Status.SCHEDULED
    if end_at and now >= end_at:
        return AuctionLot.Status.ENDED
    return AuctionLot.Status.ACTIVE


# Publish "modes" exposed to the create-lot UI (req. 9).
PUBLISH_MODES = ('draft', 'schedule', 'publish')


def _status_and_active_for_mode(mode: str, start_at, end_at) -> tuple[str, bool]:
    """Map a UI publish mode to a lot status + Listing.is_active flag."""
    if mode == 'draft':
        # A draft is hidden from public listings until published.
        return AuctionLot.Status.DRAFT, False
    if mode == 'schedule':
        return AuctionLot.Status.SCHEDULED, True
    # publish: go live now (or scheduled if the window starts in the future)
    return _compute_status(start_at, end_at), True


@transaction.atomic
def publish_lot_from_card(
    user,
    card: ArchiveFile,
    *,
    category: str,
    start_price: Decimal,
    min_bid_step: Decimal,
    start_at,
    end_at,
    buy_now_price: Decimal | None = None,
    reserve_price: Decimal | None = None,
    auto_extend: bool = False,
    extend_seconds: int = 0,
    title: str = '',
    description: str = '',
    mode: str = 'publish',
    attributes: dict | None = None,
) -> AuctionLot:
    """Create a ``Listing(type=auction)`` + :class:`AuctionLot` for an existing
    card. The source card is left untouched in its original rubric (req. 8).

    ``mode`` is one of ``draft`` / ``schedule`` / ``publish`` (req. 9).
    ``attributes`` holds auction-only item details (condition, completeness, …)
    that are stored in the lot snapshot and never written back to the card.
    """
    Listing = _import_listing_model()

    if card.owner_id != user.id:
        raise AuctionError('Вы можете выставлять на аукцион только свои карточки.')
    existing = card_blocking_lot(card)
    if existing is not None:
        # A draft is editable; scheduled/active lots are shown. Either way a
        # second lot must not be created for the same card.
        raise AuctionError(
            'Для этой карточки уже есть незавершённый лот '
            f'(#{existing.pk}, {existing.get_status_display()}).'
        )
    if category not in Listing.Category.values:
        raise AuctionError({'category': 'Выберите корректную категорию товара.'})

    status, is_active = _status_and_active_for_mode(mode, start_at, end_at)

    # The base Listing keeps its own auction_* fields (validated by its clean()).
    # AuctionLot mirrors/extends them as the auction subsystem's source of truth.
    reserve = reserve_price if reserve_price is not None else start_price
    listing = Listing(
        item=card,
        seller=user,
        type=Listing.Type.AUCTION,
        category=category,
        title=title or card.title,
        description=description,
        is_active=is_active,
        auction_start=start_at,
        auction_end=end_at,
        auction_start_price=start_price,
        auction_min_price=reserve,
        auction_step=min_bid_step,
        current_price=start_price,
    )
    listing.save()  # runs full_clean()

    lot = AuctionLot(
        listing=listing,
        status=status,
        start_price=start_price,
        current_price=start_price,
        buy_now_price=buy_now_price,
        min_bid_step=min_bid_step,
        start_at=start_at,
        end_at=end_at,
        auto_extend=auto_extend,
        extend_seconds=extend_seconds or 0,
    )
    lot.full_clean(exclude=['winner'])
    lot.capture_snapshot()
    _merge_snapshot_attributes(lot, attributes)
    lot.save()
    return lot


def _merge_snapshot_attributes(lot: AuctionLot, attributes: dict | None) -> None:
    """Merge auction-only item attributes onto the lot snapshot (not the card)."""
    if not attributes:
        return
    snapshot = lot.snapshot if isinstance(lot.snapshot, dict) else {}
    data = dict(snapshot.get('data') or {})
    for key, value in attributes.items():
        if value not in (None, ''):
            data[key] = value
    snapshot['data'] = data
    lot.snapshot = snapshot


@transaction.atomic
def create_card_in_auction(
    user,
    *,
    title: str,
    data: dict | None = None,
    category: str,
    start_price: Decimal,
    min_bid_step: Decimal,
    start_at,
    end_at,
    **lot_kwargs,
) -> AuctionLot:
    """Create a brand-new card directly inside the system «Аукцион» rubric and
    immediately publish it as a lot (req. 5). The card both lives in the system
    rubric and backs the lot.
    """
    rubric = get_or_create_auction_rubric(user)
    assert_can_create_archive_file(user)
    card = ArchiveFile(
        rubric=rubric,
        owner=user,
        title=title,
        data=data or {},
        status=ArchiveFile.Status.SELL,
    )
    card.full_clean()
    card.save()
    return publish_lot_from_card(
        user,
        card,
        category=category,
        start_price=start_price,
        min_bid_step=min_bid_step,
        start_at=start_at,
        end_at=end_at,
        title=title,
        description=str((data or {}).get('description', '')),
        **lot_kwargs,
    )


@transaction.atomic
def relist_card(user, lot: AuctionLot, **publish_kwargs) -> AuctionLot:
    """Re-list the item after cancellation or an unsold finish (req. 10).

    The old lot is kept as history; a new Listing + AuctionLot is created from
    the same card.
    """
    if lot.listing.seller_id != user.id:
        raise AuctionError('Повторно выставить лот может только его владелец.')
    if not lot.can_relist():
        raise AuctionError('Повторное выставление доступно только для отменённых '
                           'или завершённых без продажи лотов.')
    card = lot.card
    if card is None:
        raise AuctionError('Исходная карточка недоступна.')
    publish_kwargs.setdefault('category', lot.listing.category)
    return publish_lot_from_card(user, card, **publish_kwargs)


# --- Finishing a lot ----------------------------------------------------------
@transaction.atomic
def finalize_sold(lot: AuctionLot, winner, final_price: Decimal) -> AuctionLot:
    """Mark a lot sold and persist the outcome on the card (req. 12, 13).

    The winner is stored only on the lot (``lot.winner``); the card keeps the
    final price and a sale flag but never the winner's personal data.
    """
    lot.status = AuctionLot.Status.SOLD
    lot.winner = winner
    lot.current_price = final_price
    lot.save()
    lot.listing.is_active = False
    lot.listing.current_price = final_price
    lot.listing.save(update_fields=['is_active', 'current_price'])

    card = lot.card
    if card is not None:
        _write_card_auction_outcome(card, lot, sale_status='sold', final_price=final_price)
    return lot


@transaction.atomic
def finalize_ended(lot: AuctionLot) -> AuctionLot:
    """Close a lot with no sale (req. 12)."""
    lot.status = AuctionLot.Status.ENDED
    lot.save(update_fields=['status', 'updated_at'])
    lot.listing.is_active = False
    lot.listing.save(update_fields=['is_active'])
    card = lot.card
    if card is not None:
        _write_card_auction_outcome(card, lot, sale_status='ended')
    return lot


@transaction.atomic
def cancel_lot(lot: AuctionLot) -> AuctionLot:
    lot.status = AuctionLot.Status.CANCELLED
    lot.save(update_fields=['status', 'updated_at'])
    lot.listing.is_active = False
    lot.listing.save(update_fields=['is_active'])
    card = lot.card
    if card is not None:
        _write_card_auction_outcome(card, lot, sale_status='cancelled')
    return lot


def _write_card_auction_outcome(card: ArchiveFile, lot: AuctionLot, *, sale_status: str,
                                final_price: Decimal | None = None) -> None:
    """Store the auction outcome on the card, keeping it in the archive with a
    link to the lot history. Never writes winner personal data."""
    data = card.data if isinstance(card.data, dict) else {}
    outcome = {
        'lot_id': lot.pk,
        'sale_status': sale_status,
        'lot_url': lot_detail_path(lot),
        'finished_at': timezone.now().isoformat(),
    }
    if final_price is not None:
        outcome['final_price'] = str(final_price)
    data['auction'] = outcome
    card.data = data
    if sale_status == 'sold':
        card.status = ArchiveFile.Status.SOLD
    card.save(update_fields=['data', 'status', 'updated_at'])


# --- Serialization ------------------------------------------------------------
def lot_detail_path(lot: AuctionLot) -> str:
    return reverse('market_listing_detail', args=[lot.listing_id])


def serialize_card_auction_state(card: ArchiveFile, viewer=None) -> dict:
    """UI-facing auction status + the next action for a card.

    ``decision`` tells the client what «В Маркет» should do:
      * ``create``  — no unfinished lot (or only finished ones): open the new
                       lot modal (re-listing a finished lot is allowed);
      * ``edit``    — a draft exists: open it for editing;
      * ``blocked`` — a scheduled/active lot exists: show its status + open it.
    """
    blocking = card_blocking_lot(card)
    latest = latest_lot_for_card(card)

    # No unfinished lot — creation/re-listing is allowed.
    if blocking is None:
        state = {
            'has_lot': latest is not None,
            'decision': 'create',
            'status': None,
            'status_label': None,
            'actions': {},
        }
        if latest is not None:
            detail_path = lot_detail_path(latest)
            is_owner = bool(viewer) and getattr(viewer, 'id', None) == latest.listing.seller_id
            state.update({
                'lot_id': latest.pk,
                'listing_id': latest.listing_id,
                'status': latest.status,
                'status_label': latest.get_status_display(),
                'lot_url': detail_path,
                'actions': {'open': detail_path, 'share': detail_path},
            })
            if latest.status == AuctionLot.Status.SOLD:
                state['final_price'] = str(latest.current_price) if latest.current_price is not None else None
                # Winner identity is owner-only; never exposed to other users.
                state['winner_visible'] = is_owner
        return state

    is_owner = bool(viewer) and getattr(viewer, 'id', None) == blocking.listing.seller_id
    detail_path = lot_detail_path(blocking)
    decision = 'edit' if blocking.status == AuctionLot.Status.DRAFT else 'blocked'
    state = {
        'has_lot': True,
        'decision': decision,
        'lot_id': blocking.pk,
        'listing_id': blocking.listing_id,
        'status': blocking.status,
        'status_label': blocking.get_status_display(),
        'lot_url': detail_path,
        'current_price': str(blocking.current_price) if blocking.current_price is not None else None,
        'actions': {'open': detail_path, 'share': detail_path},
    }
    if decision == 'edit' and is_owner:
        snapshot = blocking.snapshot if isinstance(blocking.snapshot, dict) else {}
        state['draft'] = {
            'lot_id': blocking.pk,
            'category': blocking.listing.category,
            'description': blocking.listing.description or '',
            'start_price': str(blocking.start_price),
            'min_bid_step': str(blocking.min_bid_step),
            'buy_now_price': str(blocking.buy_now_price) if blocking.buy_now_price is not None else '',
            'start_at': blocking.start_at.isoformat() if blocking.start_at else '',
            'end_at': blocking.end_at.isoformat() if blocking.end_at else '',
            'attributes': snapshot.get('data') or {},
        }
    return state


def serialize_lot_public(lot: AuctionLot, viewer=None) -> dict:
    """Public lot payload that hides the winner's personal data (req. 13)."""
    is_owner = bool(viewer) and getattr(viewer, 'id', None) == lot.listing.seller_id
    payload = {
        'lot_id': lot.pk,
        'listing_id': lot.listing_id,
        'status': lot.status,
        'status_label': lot.get_status_display(),
        'start_price': str(lot.start_price),
        'current_price': str(lot.current_price) if lot.current_price is not None else None,
        'buy_now_price': str(lot.buy_now_price) if lot.buy_now_price is not None else None,
        'min_bid_step': str(lot.min_bid_step),
        'start_at': lot.start_at.isoformat() if lot.start_at else None,
        'end_at': lot.end_at.isoformat() if lot.end_at else None,
        'snapshot': lot.snapshot,
        'snapshot_images': lot.snapshot_images,
    }
    if lot.winner_id and is_owner:
        payload['winner_id'] = lot.winner_id
    return payload


# --- Eligible archive cards for the create-lot picker (req. 5, 6) -------------
def eligible_cards_for_user(user):
    """Cards the user may put up for auction.

    Excludes cards already in a scheduled/active auction (req. 6). Cards are
    owner-scoped, so inaccessible cards are never returned. The archive SPA
    keeps "deleted" cards out of the DB, so DB cards are inherently live.
    """
    busy_card_ids = AuctionLot.objects.filter(
        listing__seller=user, status__in=ACTIVE_LOCK_STATUSES
    ).values_list('listing__item_id', flat=True)
    return (
        ArchiveFile.objects.filter(owner=user)
        .exclude(pk__in=busy_card_ids)
        .select_related('rubric')
        .prefetch_related('images')
        .order_by('-created_at')
    )


def serialize_eligible_card(card: ArchiveFile) -> dict:
    first_image = card.images.all()[:1]
    thumb = first_image[0].image.url if first_image and first_image[0].image else ''
    data = card.data if isinstance(card.data, dict) else {}
    return {
        'id': card.pk,
        'title': card.title,
        'rubric': card.rubric.name if card.rubric_id else '',
        'thumb': thumb,
        'description': str(data.get('description', '')),
    }


# --- Bidding, buy-now, pre-bid editing ---------------------------------------
def has_bids(lot: AuctionLot) -> bool:
    return lot.listing.bids.exists()


@transaction.atomic
def place_bid(user, lot: AuctionLot, amount):
    """Place a bid through the existing ``market.Bid`` model and sync prices."""
    from market.models import Bid

    now = timezone.now()
    # A scheduled lot whose window has opened becomes active on first bid.
    if lot.status == AuctionLot.Status.SCHEDULED and lot.start_at and now >= lot.start_at:
        lot.status = AuctionLot.Status.ACTIVE
        lot.save(update_fields=['status', 'updated_at'])
    if lot.status != AuctionLot.Status.ACTIVE:
        raise AuctionError('Ставки доступны только для активного лота.')

    bid = Bid(listing=lot.listing, bidder=user, amount=amount)
    bid.save()  # validates self-bid, step and window via Bid.clean()

    lot.current_price = bid.amount
    lot.save(update_fields=['current_price', 'updated_at'])
    lot.listing.current_price = bid.amount
    lot.listing.save(update_fields=['current_price'])
    return bid


@transaction.atomic
def buy_now(user, lot: AuctionLot):
    """Instant purchase at ``buy_now_price`` (req. 3 «Купить сейчас»)."""
    if lot.buy_now_price is None:
        raise AuctionError('Для этого лота не задана цена моментальной покупки.')
    if lot.status != AuctionLot.Status.ACTIVE:
        raise AuctionError('Моментальная покупка доступна только для активного лота.')
    if lot.listing.seller_id == user.id:
        raise AuctionError('Нельзя купить собственный лот.')
    return finalize_sold(lot, user, lot.buy_now_price)


EDITABLE_BEFORE_BID = ('description', 'start_price', 'min_bid_step', 'start_at', 'end_at', 'buy_now_price')


@transaction.atomic
def edit_lot_before_bids(user, lot: AuctionLot, *, mode: str | None = None,
                         attributes: dict | None = None, photos=None, **fields) -> AuctionLot:
    """Edit a lot's description, photos and bidding parameters.

    Allowed only while the lot has no bids (req. 11). Once a bid exists the main
    conditions are frozen. ``mode`` may transition a draft to ``publish`` /
    ``schedule``; ``attributes`` updates the auction-only item details.
    """
    if lot.listing.seller_id != user.id:
        raise AuctionError('Изменять лот может только его владелец.')
    if has_bids(lot):
        raise AuctionError('После первой ставки основные условия лота изменить нельзя.')

    for name in EDITABLE_BEFORE_BID:
        if name in fields and fields[name] is not None:
            setattr(lot, name, fields[name])
    lot.clean()

    if 'start_price' in fields and fields['start_price'] is not None:
        new_start = fields['start_price']
        lot.current_price = new_start
        lot.listing.auction_start_price = new_start
        lot.listing.current_price = new_start
        # Keep the listing reserve (auction_min_price) at least the start price,
        # otherwise market.Listing.clean() rejects the change.
        if lot.listing.auction_min_price is None or lot.listing.auction_min_price < new_start:
            lot.listing.auction_min_price = new_start
    if 'min_bid_step' in fields and fields['min_bid_step'] is not None:
        lot.listing.auction_step = fields['min_bid_step']
    if 'start_at' in fields and fields['start_at'] is not None:
        lot.listing.auction_start = fields['start_at']
    if 'end_at' in fields and fields['end_at'] is not None:
        lot.listing.auction_end = fields['end_at']
    if 'description' in fields and fields['description'] is not None:
        lot.listing.description = fields['description']
    if fields.get('title'):
        lot.listing.title = fields['title']

    # Publishing a draft from the edit modal (req: «Опубликовать» on a draft).
    if mode in ('publish', 'schedule'):
        status, is_active = _status_and_active_for_mode(mode, lot.start_at, lot.end_at)
        lot.status = status
        lot.listing.is_active = is_active

    lot.listing.save()
    lot.capture_snapshot()  # refresh the frozen view from the (possibly edited) card
    _merge_snapshot_attributes(lot, attributes)
    lot.save()
    return lot


# --- Anonymized bid history (req. 3) -----------------------------------------
def bid_history(lot: AuctionLot) -> list[dict]:
    """Bid history with anonymized participants (stable per bidder)."""
    bids = list(lot.listing.bids.select_related('bidder').all())
    labels: dict[int, str] = {}
    history: list[dict] = []
    for bid in bids:
        if bid.bidder_id not in labels:
            labels[bid.bidder_id] = f'Участник {len(labels) + 1}'
        history.append({
            'when': bid.created_at,
            'bidder': labels[bid.bidder_id],
            'amount': bid.amount,
        })
    return history
