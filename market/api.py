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

from core.models import ArchiveFile
from core.utils import moderation

from .models import Bid, Listing


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

    listing.current_price = bid.amount
    listing.save(update_fields=["current_price"])

    return JsonResponse({"ok": True, "redirect": reverse("market_listing_detail", args=[listing.pk])})
