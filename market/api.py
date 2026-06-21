"""Implements JSON endpoints replacing the Java market REST controllers."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import make_aware
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.models import ArchiveFile
from core.utils import moderation

from .models import Bid, Listing
from .services import auction as auction_service
from .services import bidding as bidding_service


def _json_error(message: str, *, status: int = 400, field: str | None = None) -> JsonResponse:
    payload = {"ok": False, "errors": {}}
    if field:
        payload["errors"][field] = message
    else:
        payload["errors"]["__all__"] = message
    return JsonResponse(payload, status=status)


def _parse_decimal(value, field: str, errors: dict[str, str]) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        errors[field] = "Некорректное числовое значение."
        return None


def _parse_datetime(value, field: str, errors: dict[str, str]):
    if not value:
        errors[field] = "Укажите дату и время."
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        errors[field] = "Некорректный формат даты."
        return None
    if timezone.is_naive(parsed):
        parsed = make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _listing_redirect(type_code: str) -> str:
    mapping = {
        Listing.Type.SHOP: "market_shop",
        Listing.Type.AUCTION: "market_auction",
        Listing.Type.FREE: "market_free",
        Listing.Type.WANTED: "market_wanted",
        Listing.Type.SWAP: "market_swap",
    }
    url_name = mapping.get(type_code, "market_shop")
    return reverse(url_name)


@login_required
@transaction.atomic
def listing_create(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except json.JSONDecodeError:
        return _json_error("Некорректный JSON.")

    file_id = payload.get("file_id")
    listing_type = payload.get("type")
    if not file_id:
        return _json_error("Не указан файл.", field="file_id")
    if not listing_type:
        return _json_error("Не указан тип объявления.", field="type")

    item = get_object_or_404(
        ArchiveFile.objects.select_related("rubric__profile__user"),
        pk=file_id,
    )
    owner = item.rubric.profile.user
    if owner != request.user:
        return _json_error("Вы можете публиковать только свои файлы.", status=403)

    category = payload.get("category") or ""
    if category not in Listing.Category.values:
        return _json_error("Обязательное поле.", field="category")

    listing = Listing(
        item=item,
        seller=request.user,
        type=listing_type,
        category=category,
        title=payload.get("title") or item.title,
        description=payload.get("description", ""),
    )

    errors: dict[str, str] = {}

    if listing.type in {Listing.Type.SHOP, Listing.Type.WANTED}:
        price = _parse_decimal(payload.get("price"), "price", errors)
        listing.price = price
    elif listing.type == Listing.Type.FREE:
        listing.price = None
    elif listing.type == Listing.Type.SWAP:
        wishlist = payload.get("swap_wishlist", "")
        listing.swap_wishlist = wishlist
    elif listing.type == Listing.Type.AUCTION:
        listing.auction_start = _parse_datetime(payload.get("auction_start"), "auction_start", errors)
        listing.auction_end = _parse_datetime(payload.get("auction_end"), "auction_end", errors)
        listing.auction_start_price = _parse_decimal(payload.get("auction_start_price"), "auction_start_price", errors)
        listing.auction_min_price = _parse_decimal(payload.get("auction_min_price"), "auction_min_price", errors)
        listing.auction_step = _parse_decimal(payload.get("auction_step"), "auction_step", errors)
        listing.current_price = listing.auction_start_price

    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)

    moderation_errors: dict[str, str] = {}
    for field_name, value in (
        ("title", listing.title or ""),
        ("description", listing.description or ""),
        ("swap_wishlist", listing.swap_wishlist or ""),
    ):
        if value:
            try:
                moderation.ensure_text_allowed(value, field=field_name)
            except ValidationError as exc:
                moderation_errors[field_name] = exc.messages[0]

    if moderation_errors:
        return JsonResponse({"ok": False, "errors": moderation_errors}, status=400)

    try:
        listing.save()
    except ValidationError as exc:
        return JsonResponse({"ok": False, "errors": exc.message_dict}, status=400)

    return JsonResponse({"ok": True, "redirect": _listing_redirect(listing.type), "listing_id": listing.pk})


@login_required
@transaction.atomic
def auction_bid(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except json.JSONDecodeError:
        return _json_error("Некорректный JSON.")

    listing_id = payload.get("listing_id")
    amount_raw = payload.get("amount")
    if not listing_id:
        return _json_error("Не указан лот.", field="listing_id")

    listing = get_object_or_404(
        Listing.objects.select_for_update().select_related("seller"),
        pk=listing_id,
    )
    if listing.type != Listing.Type.AUCTION:
        return _json_error("Ставки разрешены только для аукционов.", status=400)
    if not listing.is_active:
        return _json_error("Лот неактивен.")

    errors: dict[str, str] = {}
    amount = _parse_decimal(amount_raw, "amount", errors)
    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)

    bid = Bid(listing=listing, bidder=request.user, amount=amount)
    try:
        bid.save()
    except ValidationError as exc:
        return JsonResponse({"ok": False, "errors": exc.message_dict}, status=400)

    base_price = listing.current_price if listing.current_price is not None else listing.auction_start_price
    listing.current_price = (base_price or Decimal("0")) + bid.amount
    listing.save(update_fields=["current_price"])

    return JsonResponse({"ok": True, "redirect": reverse("market_listing_detail", args=[listing.pk])})


# --- Auction draft → publish API ---------------------------------------------
import json as _json  # local alias; module already parses JSON elsewhere


def _load_json(request: HttpRequest) -> dict:
    try:
        return _json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def _draft_error(exc: auction_service.DraftError) -> JsonResponse:
    return JsonResponse({"ok": False, "errors": exc.errors}, status=exc.status)


def _validation_error(exc: ValidationError) -> JsonResponse:
    if hasattr(exc, "message_dict"):
        errors = exc.message_dict
    else:
        errors = {"__all__": exc.messages}
    return JsonResponse({"ok": False, "errors": errors}, status=400)


@login_required
@require_GET
def auction_card_status(request: HttpRequest, file_id: int) -> JsonResponse:
    """Read-only auction status for an archive card (creates no draft)."""
    card = ArchiveFile.objects.filter(pk=file_id, owner=request.user).first()
    if card is None:
        return JsonResponse({"ok": True, "has_lot": False})
    return JsonResponse(auction_service.card_auction_state(request.user, card))


@login_required
@require_GET
def auction_card_status_by_card(request: HttpRequest) -> JsonResponse:
    """Read-only auction status by the archive SPA card id (?card_id=...)."""
    card = auction_service.archive_file_by_card_id(request.user, request.GET.get("card_id"))
    if card is None:
        return JsonResponse({"ok": True, "has_lot": False})
    return JsonResponse(auction_service.card_auction_state(request.user, card))


@login_required
@require_POST
def auction_draft_create(request: HttpRequest) -> JsonResponse:
    """POST /market/api/auction/draft/ — get or create a draft for a card.

    Accepts either a numeric ``file_id`` (existing ArchiveFile.pk) or a ``card``
    payload from the archive SPA (``{card_id, title, description, images, ...}``)
    which is materialised into a real ArchiveFile first.
    """
    payload = _load_json(request)
    card = payload.get("card")
    file_id = payload.get("file_id")
    try:
        with transaction.atomic():
            if isinstance(card, dict):
                file_id = auction_service.materialize_archive_file(request.user, card).pk
            if not file_id:
                return _json_error("Не указана карточка.", field="file_id")
            data = auction_service.get_or_create_draft(request.user, file_id)
    except auction_service.DraftError as exc:
        return _draft_error(exc)
    except ValidationError as exc:
        return _validation_error(exc)
    return JsonResponse({"ok": True, **data})


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def auction_draft_manage(request: HttpRequest, listing_id: int) -> JsonResponse:
    """GET / PATCH / DELETE /market/api/auction/draft/<listing_id>/."""
    try:
        if request.method == "GET":
            listing = Listing.objects.filter(pk=listing_id, type=Listing.Type.AUCTION).first()
            if listing is None:
                return _json_error("Лот не найден.", status=404, field="listing_id")
            if listing.seller_id != request.user.id:
                return _json_error("Недостаточно прав.", status=403, field="listing_id")
            return JsonResponse({"ok": True, **auction_service.serialize_draft_detail(listing)})

        with transaction.atomic():
            listing = Listing.objects.select_for_update().filter(pk=listing_id, type=Listing.Type.AUCTION).first()
            if listing is None:
                return _json_error("Лот не найден.", status=404, field="listing_id")
            if request.method == "PATCH":
                result = {"ok": True, **auction_service.update_draft(request.user, listing, _load_json(request))}
            else:  # DELETE
                auction_service.delete_draft(request.user, listing)
                result = {"ok": True}
        return JsonResponse(result)
    except auction_service.DraftError as exc:
        return _draft_error(exc)


@login_required
@require_POST
def auction_draft_publish(request: HttpRequest, listing_id: int) -> JsonResponse:
    """POST /market/api/auction/draft/<listing_id>/publish/."""
    try:
        with transaction.atomic():
            listing = Listing.objects.select_for_update().filter(pk=listing_id, type=Listing.Type.AUCTION).first()
            if listing is None:
                return _json_error("Лот не найден.", status=404, field="listing_id")
            result = auction_service.publish_draft(request.user, listing)
        return JsonResponse({"ok": True, **result})
    except auction_service.DraftError as exc:
        return _draft_error(exc)


# --- Auction bidding API -----------------------------------------------------
def _bid_error(exc: bidding_service.BidError) -> JsonResponse:
    body = {"ok": False, "code": exc.code, "errors": {"amount": exc.message}}
    if exc.current_price is not None:
        body["current_price"] = str(exc.current_price)
    if exc.minimum_bid is not None:
        body["minimum_bid"] = str(exc.minimum_bid)
    return JsonResponse(body, status=exc.status)


@require_GET
def auction_state(request: HttpRequest, listing_id: int) -> JsonResponse:
    """GET /market/api/auction/<id>/state/ — public auction state (no PII)."""
    listing = Listing.objects.filter(pk=listing_id, type=Listing.Type.AUCTION).first()
    if listing is None:
        return JsonResponse({"ok": False, "code": "not_found", "errors": {"__all__": "Лот не найден."}}, status=404)
    bidding_service.sync_auction_status(listing)
    return JsonResponse({"ok": True, **bidding_service.serialize_state(request.user, listing)})


@require_GET
def auction_bids(request: HttpRequest, listing_id: int) -> JsonResponse:
    """GET /market/api/auction/<id>/bids/ — anonymised bid history."""
    listing = Listing.objects.filter(pk=listing_id, type=Listing.Type.AUCTION).first()
    if listing is None:
        return JsonResponse({"ok": False, "errors": {"__all__": "Лот не найден."}}, status=404)
    return JsonResponse({"ok": True, "bids": bidding_service.serialize_bids(listing)})


@require_POST
def auction_bid_place(request: HttpRequest, listing_id: int) -> JsonResponse:
    """POST /market/api/auction/<id>/bid/ — place a bid (authenticated)."""
    # Enforce auth here (instead of @login_required) to return a JSON 401 with a
    # stable API code rather than an HTML login redirect.
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "code": "authentication_required",
                             "errors": {"amount": "Войдите, чтобы делать ставки."}}, status=401)

    payload = _load_json(request)
    try:
        amount = bidding_service.parse_amount(payload.get("amount"))
    except bidding_service.BidError as exc:
        return _bid_error(exc)

    seen_minimum = None
    raw_seen = payload.get("seen_minimum")
    if raw_seen not in (None, ""):
        try:
            seen_minimum = Decimal(str(raw_seen))
        except (InvalidOperation, TypeError, ValueError):
            seen_minimum = None

    seen_current_price = None
    raw_seen_price = payload.get("seen_current_price")
    if raw_seen_price not in (None, ""):
        try:
            seen_current_price = Decimal(str(raw_seen_price))
        except (InvalidOperation, TypeError, ValueError):
            seen_current_price = None

    try:
        result = bidding_service.place_bid(
            request.user,
            listing_id,
            amount,
            seen_minimum=seen_minimum,
            seen_current_price=seen_current_price,
        )
    except bidding_service.BidError as exc:
        return _bid_error(exc)

    return JsonResponse({
        "ok": True,
        "bid_id": result["bid"].id,
        "current_price": str(result["current_price"]),
        "minimum_next_bid": str(result["minimum_next_bid"]),
        "bid_count": result["bid_count"],
        "is_user_leading": result["is_user_leading"],
        "auction_end": result["auction_end"].isoformat() if result["auction_end"] else None,
        "extended": result["extended"],
        "reserve_status": result["reserve_status"],
    })


# --- Seller management of a published lot -------------------------------------
@login_required
@require_http_methods(["PATCH"])
def auction_manage(request: HttpRequest, listing_id: int) -> JsonResponse:
    """PATCH /market/api/auction/<id>/manage/ — edit own published lot."""
    payload = _load_json(request)
    try:
        with transaction.atomic():
            data = auction_service.manage_edit(request.user, listing_id, payload)
        return JsonResponse({"ok": True, **data})
    except auction_service.DraftError as exc:
        return _draft_error(exc)


@login_required
@require_POST
def auction_cancel(request: HttpRequest, listing_id: int) -> JsonResponse:
    """POST /market/api/auction/<id>/cancel/ — cancel own lot (or admin)."""
    payload = _load_json(request)
    try:
        with transaction.atomic():
            data = auction_service.cancel_auction(request.user, listing_id, str(payload.get("reason") or ""))
        return JsonResponse(data)
    except auction_service.DraftError as exc:
        return _draft_error(exc)


@login_required
@require_POST
def auction_relist(request: HttpRequest, listing_id: int) -> JsonResponse:
    """POST /market/api/auction/<id>/relist/ — re-list a finished/cancelled lot."""
    try:
        with transaction.atomic():
            data = auction_service.relist(request.user, listing_id)
        return JsonResponse(data)
    except auction_service.DraftError as exc:
        return _draft_error(exc)
