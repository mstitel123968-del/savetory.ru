"""Server-side bidding mechanics for published auctions.

All state-changing work runs inside ``transaction.atomic`` with
``select_for_update`` on the listing and a re-check of the auction state after
the lock, so two simultaneous bids can never both win or corrupt the price.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from ..models import AuctionBid, Listing

logger = logging.getLogger("market.bidding")

# Reasonable upper bound (also fits the DecimalField max_digits=12).
MAX_BID = Decimal("100000000.00")
CENTS = Decimal("0.01")


class BidError(Exception):
    """Carries an API error code, message and the fresh price context."""

    def __init__(self, code, message, *, status=400, current_price=None, minimum_bid=None):
        self.code = code
        self.message = message
        self.status = status
        self.current_price = current_price
        self.minimum_bid = minimum_bid
        super().__init__(message)


# --- helpers -----------------------------------------------------------------
def _iso(value):
    return value.isoformat() if value else None


def _dec(value):
    return str(value) if value is not None else None


def format_money(value) -> str:
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def mask_username(username: str) -> str:
    """Anonymise a participant: ``Пётр`` -> ``П***р``."""
    name = (username or "").strip()
    if not name:
        return "Участник"
    if len(name) <= 2:
        return name[0] + "***"
    return name[0] + "***" + name[-1]


def parse_amount(raw) -> Decimal:
    """Validate a client amount: Decimal, 2 places, no NaN/Inf/negatives, capped."""
    if raw is None or raw == "":
        raise BidError("invalid_amount", "Укажите сумму ставки.")
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        raise BidError("invalid_amount", "Некорректная сумма ставки.")
    if amount.is_nan() or amount.is_infinite():
        raise BidError("invalid_amount", "Некорректная сумма ставки.")
    if amount <= 0:
        raise BidError("invalid_amount", "Сумма должна быть больше нуля.")
    if amount != amount.quantize(CENTS):
        raise BidError("invalid_amount", "Допустимы только два знака после запятой.")
    if amount > MAX_BID:
        raise BidError("invalid_amount", "Слишком большая сумма ставки.")
    return amount.quantize(CENTS)


# --- finalization (single completion service) --------------------------------
def _determine_result(listing: Listing):
    """Return ``(result, winner, winning_bid)`` for an ended auction."""
    leading = leading_bid(listing)
    if leading is None:
        return Listing.AuctionResult.NO_BIDS, None, None
    reserve = listing.auction_reserve_price
    price = listing.current_price if listing.current_price is not None else Decimal("0")
    if reserve is not None and price < reserve:
        # Bids exist but the reserve was not reached: no winner, keep the max bid.
        return Listing.AuctionResult.RESERVE_NOT_REACHED, None, leading
    return Listing.AuctionResult.SOLD, leading.bidder, leading


def _finalize_locked(listing: Listing, now) -> bool:
    """Apply scheduled→active / completion to an already-locked listing.

    Idempotent: a completed or cancelled lot is never re-evaluated, so a saved
    result is never overwritten.
    """
    if listing.type != Listing.Type.AUCTION:
        return False
    if listing.status in (Listing.Status.COMPLETED, Listing.Status.CANCELLED):
        return False
    started = listing.auction_start and now >= listing.auction_start
    ended = listing.auction_end and now >= listing.auction_end

    if listing.status == Listing.Status.SCHEDULED and started and not ended:
        Listing.objects.filter(pk=listing.pk).update(status=Listing.Status.ACTIVE, is_active=True)
        listing.status = Listing.Status.ACTIVE
        listing.is_active = True
        return True

    if listing.status in (Listing.Status.ACTIVE, Listing.Status.SCHEDULED) and ended:
        result, winner, winning = _determine_result(listing)
        Listing.objects.filter(pk=listing.pk).update(
            status=Listing.Status.COMPLETED, is_active=False, auction_result=result,
            winner=winner, winning_bid=winning, completed_at=now,
        )
        listing.status = Listing.Status.COMPLETED
        listing.is_active = False
        listing.auction_result = result
        listing.winner = winner
        listing.winning_bid = winning
        listing.completed_at = now
        logger.info("auction finalized listing=%s result=%s winner=%s",
                    listing.pk, result, getattr(winner, "pk", None))
        return True
    return False


@transaction.atomic
def finalize_auction(listing_or_id):
    """Authoritative completion service: lock, re-check, finalize exactly once."""
    lid = getattr(listing_or_id, "pk", listing_or_id)
    listing = Listing.objects.select_for_update().filter(pk=lid, type=Listing.Type.AUCTION).first()
    if listing is None:
        return None
    _finalize_locked(listing, timezone.now())
    return listing


def sync_auction_status(listing: Listing) -> bool:
    """Backwards-compatible wrapper: finalize the lot and refresh ``listing``."""
    if listing.type != Listing.Type.AUCTION:
        return False
    before = listing.status
    finalized = finalize_auction(listing)
    if finalized is not None and finalized.pk == listing.pk:
        for field in ("status", "is_active", "auction_end", "current_price",
                      "auction_result", "winner_id", "winning_bid_id", "completed_at"):
            setattr(listing, field, getattr(finalized, field))
    return listing.status != before


# --- pricing -----------------------------------------------------------------
def has_bids(listing: Listing) -> bool:
    return AuctionBid.objects.filter(listing=listing).exists()


def current_price_base(listing: Listing) -> Decimal:
    """Return the persisted current price, falling back to the start price."""
    return (listing.current_price if listing.current_price is not None else listing.auction_start_price) or Decimal("0")


def minimum_bid(listing: Listing) -> Decimal:
    """Return the minimal allowed bid increment."""
    return listing.auction_step or Decimal("0")


def reserve_status(listing: Listing) -> str:
    if listing.auction_reserve_price is None:
        return "not_set"
    if listing.current_price is not None and listing.current_price >= listing.auction_reserve_price:
        return "reached"
    return "not_reached"


def leading_bid(listing: Listing):
    return AuctionBid.objects.filter(listing=listing, is_winning=True).select_related("bidder").first()


def can_user_bid(user, listing: Listing):
    """Return ``(allowed, code, message)`` without mutating anything."""
    if not user or not getattr(user, "is_authenticated", False):
        return False, "authentication_required", "Войдите, чтобы делать ставки."
    if listing.type != Listing.Type.AUCTION:
        return False, "auction_not_started", "Лот не является аукционом."
    if listing.status == Listing.Status.CANCELLED:
        return False, "auction_cancelled", "Аукцион отменён."
    now = timezone.now()
    if listing.status == Listing.Status.COMPLETED or (listing.auction_end and now >= listing.auction_end):
        return False, "auction_ended", "Аукцион завершён."
    if listing.status == Listing.Status.SCHEDULED or (listing.auction_start and now < listing.auction_start):
        return False, "auction_not_started", "Аукцион ещё не начался."
    if listing.status != Listing.Status.ACTIVE:
        return False, "auction_not_started", "Аукцион недоступен для ставок."
    if listing.seller_id == user.id:
        return False, "seller_cannot_bid", "Нельзя делать ставки на собственный лот."
    return True, None, None


# --- auto-extend -------------------------------------------------------------
def apply_auto_extend(listing: Listing, now):
    """Extend the end time if a bid lands in the final window. Never extends a
    finished or cancelled auction."""
    if not listing.auction_auto_extend or listing.status != Listing.Status.ACTIVE or not listing.auction_end:
        return False, listing.auction_end
    window = timedelta(minutes=listing.auction_auto_extend_minutes or 2)
    if now >= listing.auction_end - window:
        new_end = max(listing.auction_end, now + window)
        listing.auction_end = new_end
        return True, new_end
    return False, listing.auction_end


# --- place a bid -------------------------------------------------------------
@transaction.atomic
def place_bid(
    user,
    listing_id,
    amount: Decimal,
    *,
    seen_minimum: Decimal | None = None,
    seen_current_price: Decimal | None = None,
) -> dict:
    listing = Listing.objects.select_for_update().filter(pk=listing_id, type=Listing.Type.AUCTION).first()
    if listing is None:
        raise BidError("auction_not_started", "Лот не найден.", status=404)

    # Re-evaluate everything AFTER the row is locked (finalize if it just ended).
    _finalize_locked(listing, timezone.now())
    allowed, code, message = can_user_bid(user, listing)
    if not allowed:
        status = 401 if code == "authentication_required" else (403 if code == "seller_cannot_bid" else 400)
        raise BidError(code, message, status=status)

    if amount is None or amount <= 0:
        raise BidError("invalid_amount", "Некорректная сумма ставки.")

    now = timezone.now()
    min_bid = minimum_bid(listing)
    base_price = current_price_base(listing)
    leader = leading_bid(listing)

    if seen_current_price is not None and seen_current_price != base_price:
        raise BidError("concurrent_bid_conflict", "Цена изменилась, пока вы делали ставку.",
                       current_price=base_price, minimum_bid=min_bid)

    # The current leader may only re-bid if the amount rises by at least a step.
    if leader is not None and leader.bidder_id == user.id:
        required = min_bid
        if amount < required:
            raise BidError("already_leading", "Вы уже лидируете — повысьте ставку минимум на шаг.",
                           current_price=base_price, minimum_bid=required)

    if amount < min_bid:
        # A bid that was sufficient against the client's last-seen minimum but is
        # no longer enough means another bid landed first (a race).
        if seen_minimum is not None and amount >= seen_minimum:
            raise BidError("concurrent_bid_conflict", "Цена изменилась, пока вы делали ставку.",
                           current_price=base_price, minimum_bid=min_bid)
        raise BidError("bid_too_low", f"Минимальная ставка — {format_money(min_bid)} ₽",
                       current_price=base_price, minimum_bid=min_bid)

    previous_price = base_price
    new_price = base_price + amount
    AuctionBid.objects.filter(listing=listing, is_winning=True).update(is_winning=False)
    bid = AuctionBid.objects.create(
        listing=listing, bidder=user, amount=amount, previous_price=previous_price, is_winning=True,
    )
    listing.current_price = new_price
    extended, new_end = apply_auto_extend(listing, now)

    update_fields = {"current_price": new_price}
    if extended:
        update_fields["auction_end"] = listing.auction_end
    Listing.objects.filter(pk=listing.pk).update(**update_fields)

    logger.info(
        "auction bid placed listing=%s bidder=%s amount=%s current_price=%s extended=%s",
        listing.pk, user.pk, amount, new_price, extended,
    )

    return {
        "bid": bid,
        "current_price": new_price,
        "minimum_next_bid": min_bid,
        "bid_count": AuctionBid.objects.filter(listing=listing).count(),
        "is_user_leading": True,
        "auction_end": listing.auction_end,
        "extended": extended,
        "reserve_status": reserve_status(listing),
    }


# --- serialization -----------------------------------------------------------
def serialize_state(user, listing: Listing) -> dict:
    allowed, code, _message = can_user_bid(user, listing)
    leader = leading_bid(listing)
    authed = bool(user and getattr(user, "is_authenticated", False))
    return {
        "listing_id": listing.pk,
        "status": listing.status,
        "auction_start": _iso(listing.auction_start),
        "auction_end": _iso(listing.auction_end),
        "start_price": _dec(listing.auction_start_price),
        "current_price": _dec(current_price_base(listing)),
        "minimum_bid": _dec(minimum_bid(listing)),
        "bid_count": AuctionBid.objects.filter(listing=listing).count(),
        "has_bids": has_bids(listing),
        "auto_extend": bool(listing.auction_auto_extend),
        "reserve_status": reserve_status(listing),
        "is_seller": bool(authed and listing.seller_id == user.id),
        "is_leading": bool(authed and leader and leader.bidder_id == user.id),
        "can_bid": allowed,
        "bid_block_reason": code,
    }


def serialize_bids(listing: Listing) -> list[dict]:
    """Anonymised history, newest first. No email, full name or user ids."""
    bids = AuctionBid.objects.filter(listing=listing).select_related("bidder").order_by("-created_at")
    return [
        {
            "bidder": mask_username(bid.bidder.username),
            "amount": _dec(bid.amount),
            "created_at": _iso(bid.created_at),
            "is_winning": bid.is_winning,
        }
        for bid in bids
    ]
