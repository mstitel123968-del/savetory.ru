"""Business logic for the auction draft → publish flow.

Creates a draft ``Listing`` from a «Ваш архив» card, copies the card images
into independent ``ListingImage`` rows, supports partial draft editing, checks
publish readiness and publishes the lot. Kept out of ``market/api.py`` so the
HTTP layer stays thin.
"""
from __future__ import annotations

import base64
import binascii
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import make_aware

from core.models import ArchiveFile, ArchiveFileImage, Profile, Rubric
from core.services.subscriptions import assert_can_create_archive_file
from core.utils import moderation

from . import bidding
from ..models import Listing, ListingImage

logger = logging.getLogger("market.auction")

# Minimum / maximum auction duration allowed at publish time.
MIN_DURATION = timedelta(hours=1)
MAX_DURATION = timedelta(days=30)

# Fields a PATCH may touch. Anything else is rejected.
ALLOWED_PATCH_FIELDS = {
    "title", "description", "category", "condition", "location",
    "delivery_methods", "delivery_cost", "delivery_note",
    "auction_start_mode", "auction_start", "auction_end", "auction_duration_minutes",
    "auction_start_price", "auction_step", "auction_reserve_price", "auction_buy_now_price",
    "auction_auto_extend", "auction_auto_extend_minutes",
    "image_order", "cover_image_id", "excluded_image_ids",
}


class DraftError(Exception):
    """Field-keyed validation error: ``{"field": "message"}`` with HTTP status."""

    def __init__(self, errors: dict, status: int = 400):
        self.errors = errors
        self.status = status
        super().__init__(str(errors))


# --- parsing helpers ---------------------------------------------------------
def _parse_decimal(value, field, errors):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        errors[field] = "Некорректное числовое значение."
        return None


def _parse_int(value, field, errors):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors[field] = "Некорректное целое число."
        return None


def _parse_datetime(value, field, errors):
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        errors[field] = "Некорректный формат даты."
        return None
    if timezone.is_naive(parsed):
        parsed = make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _moderate(text, field, errors):
    if text:
        try:
            moderation.ensure_text_allowed(text, field=field)
        except ValidationError as exc:
            errors[field] = " ".join(exc.messages)


def _model_errors(exc: ValidationError) -> dict:
    message_dict = getattr(exc, "message_dict", None)
    if message_dict:
        return {key: " ".join(values) for key, values in message_dict.items()}
    return {"__all__": " ".join(exc.messages)}


# --- serialization -----------------------------------------------------------
def _listing_detail_url(listing: Listing) -> str:
    # The published auction's own detail page (not the generic listing page or
    # the auction list), so publish/relist redirects land on the created lot.
    return reverse("market_auction_detail", args=[listing.pk])


def _serialize_images(listing: Listing) -> list[dict]:
    images = []
    for image in listing.images.all():
        images.append({
            "id": image.id,
            "url": image.image.url if image.image else "",
            "order": image.display_order,
            "is_cover": image.is_cover,
        })
    return images


def _cover_id(listing: Listing):
    cover = listing.images.filter(is_cover=True).first()
    return cover.id if cover else None


def serialize_create_response(listing: Listing, card: ArchiveFile, published_url=None) -> dict:
    return {
        "listing_id": listing.pk,
        "status": listing.status,
        "title": listing.title,
        "description": listing.description,
        "rubric": card.rubric.name if card.rubric_id else "",
        "image_count": listing.images.count(),
        "images": _serialize_images(listing),
        "published_url": published_url,
    }


def serialize_draft_detail(listing: Listing) -> dict:
    return {
        "listing_id": listing.pk,
        "status": listing.status,
        "title": listing.title,
        "description": listing.description,
        "category": listing.category,
        "condition": listing.item_condition,
        "location": listing.location,
        "delivery_methods": listing.delivery_methods or [],
        "delivery_cost": str(listing.delivery_cost) if listing.delivery_cost is not None else None,
        "delivery_note": listing.delivery_note,
        "auction_start_mode": listing.auction_start_mode,
        "auction_start": listing.auction_start.isoformat() if listing.auction_start else None,
        "auction_end": listing.auction_end.isoformat() if listing.auction_end else None,
        "auction_duration_minutes": listing.auction_duration_minutes,
        "auction_start_price": str(listing.auction_start_price) if listing.auction_start_price is not None else None,
        "auction_step": str(listing.auction_step) if listing.auction_step is not None else None,
        "auction_buy_now_price": str(listing.auction_buy_now_price) if listing.auction_buy_now_price is not None else None,
        # Reserve price is visible to the draft owner (this endpoint is owner-only).
        "auction_reserve_price": str(listing.auction_reserve_price) if listing.auction_reserve_price is not None else None,
        "auction_auto_extend": listing.auction_auto_extend,
        "auction_auto_extend_minutes": listing.auction_auto_extend_minutes,
        "images": _serialize_images(listing),
        "cover_image_id": _cover_id(listing),
        "options": {
            "category": [{"value": v, "label": l} for v, l in Listing.Category.choices],
            "condition": [{"value": v, "label": l} for v, l in Listing.Condition.choices],
            "delivery_methods": [{"value": v, "label": l} for v, l in Listing.DeliveryMethod.choices],
            "start_mode": [{"value": v, "label": l} for v, l in Listing.StartMode.choices],
        },
    }


# --- image copying -----------------------------------------------------------
def _copy_image_file(source_afi, lot_image: ListingImage) -> None:
    """Copy the source file into the lot image via the storage API only."""
    source = source_afi.image
    if not source:
        return
    source.open("rb")
    try:
        content = source.read()
    finally:
        source.close()
    name = os.path.basename(source.name) or f"image-{source_afi.id}.jpg"
    lot_image.image.save(name, ContentFile(content), save=False)


def _ensure_single_cover(listing: Listing) -> None:
    images = list(listing.images.all())
    if not images:
        return
    covers = [img for img in images if img.is_cover]
    if not covers:
        first = images[0]
        first.is_cover = True
        first.save(update_fields=["is_cover"])
    elif len(covers) > 1:
        for extra in covers[1:]:
            extra.is_cover = False
            extra.save(update_fields=["is_cover"])


def copy_card_images_to_listing(listing: Listing, card: ArchiveFile) -> None:
    """Create a ListingImage per archive image. Idempotent: re-runs never
    duplicate (existing source links are skipped)."""
    existing_sources = set(
        ListingImage.objects.filter(listing=listing).values_list("source_image_id", flat=True)
    )
    has_cover = ListingImage.objects.filter(listing=listing, is_cover=True).exists()
    for index, afi in enumerate(card.images.all()):
        if afi.id in existing_sources:
            continue
        order = afi.display_order if afi.display_order is not None else index
        lot_image = ListingImage(listing=listing, source_image=afi, display_order=order, is_cover=False)
        _copy_image_file(afi, lot_image)
        if not has_cover:
            lot_image.is_cover = True
            has_cover = True
        lot_image.save()
    _ensure_single_cover(listing)


# --- get or create draft -----------------------------------------------------
def _published_lot(card: ArchiveFile, user):
    return (
        Listing.objects.filter(
            item=card, seller=user, type=Listing.Type.AUCTION,
            status__in=[Listing.Status.SCHEDULED, Listing.Status.ACTIVE],
        )
        .order_by("-created_at")
        .first()
    )


def _description_from_card(card: ArchiveFile) -> str:
    data = card.data if isinstance(card.data, dict) else {}
    value = data.get("description")
    return value if isinstance(value, str) else ""


def _market_source_rubric(user) -> Rubric:
    """A per-user system rubric that owns auction-materialised archive cards."""
    from auction.constants import AUCTION_FIELD_SCHEMA, AUCTION_RUBRIC_NAME, AUCTION_RUBRIC_SLUG

    profile, _ = Profile.objects.get_or_create(user=user)
    rubric, _ = Rubric.objects.get_or_create(
        profile=profile, slug=AUCTION_RUBRIC_SLUG,
        defaults={"name": AUCTION_RUBRIC_NAME, "is_system": True, "field_schema": AUCTION_FIELD_SCHEMA},
    )
    updates = []
    if rubric.name != AUCTION_RUBRIC_NAME:
        rubric.name = AUCTION_RUBRIC_NAME
        updates.append("name")
    if not rubric.is_system:
        rubric.is_system = True
        updates.append("is_system")
    if rubric.field_schema != AUCTION_FIELD_SCHEMA:
        rubric.field_schema = AUCTION_FIELD_SCHEMA
        updates.append("field_schema")
    if updates:
        rubric.save(update_fields=updates + ["updated_at"])
    return rubric


def _create_archive_images(archive_file: ArchiveFile, images: list) -> None:
    """Decode inline data-URL photos into ArchiveFileImage rows."""
    for index, item in enumerate(images):
        src = item.get("src") if isinstance(item, dict) else item
        if not isinstance(src, str) or not src.startswith("data:"):
            continue
        try:
            header, encoded = src.split(",", 1)
            content = base64.b64decode(encoded)
        except (ValueError, binascii.Error):
            continue
        if not content:
            continue
        ext = "jpg" if ("jpeg" in header or "jpg" in header) else ("webp" if "webp" in header else "png")
        afi = ArchiveFileImage(archive_file=archive_file, display_order=index)
        afi.image.save(f"market-card-{archive_file.pk}-{index}.{ext}", ContentFile(content), save=False)
        afi.save()


def materialize_archive_file(user, card: dict) -> ArchiveFile:
    """Get-or-create a real ``ArchiveFile`` for a JSON archive card.

    The archive SPA keeps cards only in ``ArchiveState`` JSON, so no
    ``ArchiveFile`` row exists until a card is taken to the market. We create
    one (idempotently, keyed by the SPA card id) and copy its photos into
    ``ArchiveFileImage`` rows so the draft flow has a real ``ArchiveFile.pk``.
    """
    card_id = str(card.get("card_id") or "").strip()
    title = str(card.get("title") or "").strip() or "Лот"
    description = str(card.get("description") or "")
    images = card.get("images") if isinstance(card.get("images"), list) else []

    if card_id:
        existing = ArchiveFile.objects.filter(owner=user, data__archive_card_id=card_id).first()
        if existing is not None:
            return existing

    assert_can_create_archive_file(user)
    archive_file = ArchiveFile(
        rubric=_market_source_rubric(user), owner=user, title=title,
        data={"description": description, **({"archive_card_id": card_id} if card_id else {})},
        status=ArchiveFile.Status.KEEP,
    )
    try:
        with transaction.atomic():
            archive_file.save()
    except IntegrityError:
        # Same title/content already exists for this user — adopt that card.
        archive_file = ArchiveFile.objects.filter(
            owner=user, normalized_title=moderation.normalise_text(title)
        ).first()
        if archive_file is None:
            raise DraftError({"file_id": "Не удалось сохранить карточку."}, status=400)
        if card_id and (not isinstance(archive_file.data, dict) or archive_file.data.get("archive_card_id") != card_id):
            merged = dict(archive_file.data) if isinstance(archive_file.data, dict) else {}
            merged["archive_card_id"] = card_id
            archive_file.data = merged
            archive_file.save(update_fields=["data", "updated_at"])
        return archive_file
    _create_archive_images(archive_file, images)
    return archive_file


def archive_file_by_card_id(user, card_id) -> ArchiveFile | None:
    cid = str(card_id or "").strip()
    if not cid:
        return None
    return ArchiveFile.objects.filter(owner=user, data__archive_card_id=cid).first()


def get_or_create_draft(user, file_id) -> dict:
    """Return an existing draft/published lot for the card, or create a draft.

    Must run inside ``transaction.atomic`` (uses ``select_for_update``).
    """
    try:
        card = ArchiveFile.objects.select_for_update().select_related("rubric").get(pk=file_id)
    except (ArchiveFile.DoesNotExist, ValueError, TypeError):
        raise DraftError({"file_id": "Карточка не найдена."}, status=404)

    if card.owner_id != user.id:
        raise DraftError({"file_id": "Недостаточно прав для этой карточки."}, status=403)

    # A scheduled/active lot already exists — never create a duplicate.
    published = _published_lot(card, user)
    if published is not None:
        return serialize_create_response(published, card, published_url=_listing_detail_url(published))

    draft = (
        Listing.objects.filter(item=card, seller=user, type=Listing.Type.AUCTION, status=Listing.Status.DRAFT)
        .order_by("-created_at")
        .first()
    )
    if draft is None:
        draft = Listing(
            item=card, seller=user, type=Listing.Type.AUCTION, status=Listing.Status.DRAFT,
            is_active=False, title=card.title, description=_description_from_card(card),
        )
        draft.save()
    copy_card_images_to_listing(draft, card)
    return serialize_create_response(draft, card, published_url=None)


def _card_status_label(listing: Listing) -> str:
    """Archive-card badge text for an auction lot (incl. final results)."""
    if listing.status == Listing.Status.DRAFT:
        return "Черновик"
    if listing.status == Listing.Status.SCHEDULED:
        return "Ожидает начала"
    if listing.status == Listing.Status.ACTIVE:
        return "Аукцион идёт"
    if listing.status == Listing.Status.CANCELLED:
        return "Отменён"
    if listing.status == Listing.Status.COMPLETED:
        result_labels = {
            Listing.AuctionResult.SOLD: "Продано",
            Listing.AuctionResult.RESERVE_NOT_REACHED: "Резерв не достигнут",
            Listing.AuctionResult.NO_BIDS: "Не продано",
        }
        return result_labels.get(listing.auction_result, "Завершён")
    return listing.get_status_display()


def card_auction_state(user, card: ArchiveFile) -> dict:
    """Read-only auction status for a card (no draft is created).

    Drives the archive card badge and the «В Маркет» / «На аукционе» action.
    Finished/cancelled lots are reported for the badge but do not block starting
    a new auction (re-listing).
    """
    qs = Listing.objects.filter(item=card, seller=user, type=Listing.Type.AUCTION)
    listing = (
        qs.filter(status=Listing.Status.DRAFT).order_by("-created_at").first()
        or qs.filter(status__in=[Listing.Status.SCHEDULED, Listing.Status.ACTIVE]).order_by("-created_at").first()
        or qs.filter(status__in=[Listing.Status.COMPLETED, Listing.Status.CANCELLED]).order_by("-created_at").first()
    )
    if listing is None:
        return {"ok": True, "has_lot": False}
    # Lazily finalize a live lot whose time has elapsed so the badge is correct.
    if listing.status in (Listing.Status.SCHEDULED, Listing.Status.ACTIVE):
        bidding.finalize_auction(listing)
        listing.refresh_from_db()
    return {
        "ok": True,
        "has_lot": True,
        "listing_id": listing.pk,
        "status": listing.status,
        "status_label": _card_status_label(listing),
        "is_draft": listing.status == Listing.Status.DRAFT,
        "is_finished": listing.status in (Listing.Status.COMPLETED, Listing.Status.CANCELLED),
        "listing_url": _listing_detail_url(listing),
    }


# --- partial update ----------------------------------------------------------
def update_draft(user, listing: Listing, payload: dict) -> dict:
    if listing.seller_id != user.id:
        raise DraftError({"__all__": "Недостаточно прав."}, status=403)
    if listing.status != Listing.Status.DRAFT:
        raise DraftError({"__all__": "Редактировать можно только черновик."}, status=400)

    unknown = [key for key in payload if key not in ALLOWED_PATCH_FIELDS]
    if unknown:
        raise DraftError({key: "Неизвестное поле." for key in unknown})

    errors: dict = {}
    _apply_scalar_fields(listing, payload, errors)
    if errors:
        raise DraftError(errors)

    try:
        listing.save()
    except ValidationError as exc:
        raise DraftError(_model_errors(exc))

    _apply_image_changes(listing, payload)
    return serialize_draft_detail(listing)


def _apply_scalar_fields(listing: Listing, payload: dict, errors: dict) -> None:
    """Apply the (validated) scalar fields present in ``payload`` to ``listing``.

    Shared by the draft editor and the published-lot manage editor.
    """
    if "title" in payload:
        listing.title = str(payload["title"] or "")
        _moderate(listing.title, "title", errors)
    if "description" in payload:
        listing.description = str(payload["description"] or "")
        _moderate(listing.description, "description", errors)
    if "delivery_note" in payload:
        listing.delivery_note = str(payload["delivery_note"] or "")
        _moderate(listing.delivery_note, "delivery_note", errors)
    if "location" in payload:
        listing.location = str(payload["location"] or "")

    if "category" in payload:
        value = str(payload["category"] or "")
        if value and value not in Listing.Category.values:
            errors["category"] = "Некорректная категория."
        else:
            listing.category = value
    if "condition" in payload:
        value = str(payload["condition"] or "")
        if value and value not in Listing.Condition.values:
            errors["condition"] = "Некорректное состояние."
        else:
            listing.item_condition = value
    if "auction_start_mode" in payload:
        value = str(payload["auction_start_mode"] or "")
        if value not in Listing.StartMode.values:
            errors["auction_start_mode"] = "Некорректный режим начала."
        else:
            listing.auction_start_mode = value

    if "delivery_methods" in payload:
        methods = payload["delivery_methods"]
        if not isinstance(methods, list):
            errors["delivery_methods"] = "Ожидается список способов передачи."
        else:
            seen: set = set()
            cleaned: list = []
            for method in methods:
                if method not in Listing.DeliveryMethod.values:
                    errors["delivery_methods"] = "Недопустимый способ передачи."
                    break
                if method in seen:
                    errors["delivery_methods"] = "Способы передачи не должны повторяться."
                    break
                seen.add(method)
                cleaned.append(method)
            else:
                listing.delivery_methods = cleaned

    for key, attr in (("delivery_cost", "delivery_cost"), ("auction_start_price", "auction_start_price"),
                      ("auction_step", "auction_step"), ("auction_reserve_price", "auction_reserve_price"),
                      ("auction_buy_now_price", "auction_buy_now_price")):
        if key in payload:
            parsed = _parse_decimal(payload[key], key, errors)
            if key not in errors:
                setattr(listing, attr, parsed)

    for key in ("auction_start", "auction_end"):
        if key in payload:
            parsed = _parse_datetime(payload[key], key, errors)
            if key not in errors:
                setattr(listing, key, parsed)

    for key in ("auction_duration_minutes", "auction_auto_extend_minutes"):
        if key in payload:
            parsed = _parse_int(payload[key], key, errors)
            if key not in errors:
                setattr(listing, key, parsed)

    if "auction_auto_extend" in payload:
        listing.auction_auto_extend = bool(payload["auction_auto_extend"])


def _apply_image_changes(listing: Listing, payload: dict) -> None:
    errors: dict = {}

    if "excluded_image_ids" in payload:
        ids = payload["excluded_image_ids"]
        if not isinstance(ids, list):
            errors["excluded_image_ids"] = "Ожидается список идентификаторов."
        else:
            # Deletes ListingImage rows only — ArchiveFileImage is never touched.
            ListingImage.objects.filter(listing=listing, id__in=ids).delete()

    if "image_order" in payload and "image_order" not in errors:
        order = payload["image_order"]
        if not isinstance(order, list):
            errors["image_order"] = "Ожидается список идентификаторов."
        else:
            owned = {img.id: img for img in ListingImage.objects.filter(listing=listing)}
            for index, image_id in enumerate(order):
                image = owned.get(image_id)
                if image is None:
                    errors["image_order"] = "Изображение не принадлежит лоту."
                    break
                if image.display_order != index:
                    image.display_order = index
                    image.save(update_fields=["display_order"])

    if "cover_image_id" in payload and "cover_image_id" not in errors:
        cover_id = payload["cover_image_id"]
        target = ListingImage.objects.filter(listing=listing, id=cover_id).first()
        if target is None:
            errors["cover_image_id"] = "Обложка не принадлежит лоту."
        else:
            ListingImage.objects.filter(listing=listing, is_cover=True).exclude(pk=target.pk).update(is_cover=False)
            if not target.is_cover:
                target.is_cover = True
                target.save(update_fields=["is_cover"])

    if errors:
        raise DraftError(errors)

    # After reordering/exclusion exactly one cover must remain.
    _ensure_single_cover(listing)


# --- readiness & publish -----------------------------------------------------
def _effective_window(listing: Listing, now):
    if listing.auction_start_mode == Listing.StartMode.NOW:
        start = now
        if listing.auction_duration_minutes:
            end = now + timedelta(minutes=listing.auction_duration_minutes)
        else:
            end = listing.auction_end
    else:
        start = listing.auction_start
        if listing.auction_end is not None:
            end = listing.auction_end
        elif listing.auction_duration_minutes and start:
            end = start + timedelta(minutes=listing.auction_duration_minutes)
        else:
            end = None
    return start, end


def check_readiness(listing: Listing) -> dict:
    errors: dict = {}
    now = timezone.now()

    images = list(listing.images.all())
    if not images:
        errors["images"] = "Добавьте хотя бы одно изображение."
    elif not any(img.is_cover for img in images):
        errors["cover_image_id"] = "Выберите обложку."

    if not (listing.title or "").strip():
        errors["title"] = "Укажите название."
    if not listing.category:
        errors["category"] = "Выберите категорию."
    if not listing.item_condition:
        errors["condition"] = "Укажите состояние предмета."

    if listing.auction_start_price is None or listing.auction_start_price <= 0:
        errors["auction_start_price"] = "Укажите стартовую цену больше нуля."
    if listing.auction_step is None or listing.auction_step <= 0:
        errors["auction_step"] = "Укажите шаг ставки больше нуля."
    if (listing.auction_reserve_price is not None and listing.auction_start_price is not None
            and listing.auction_reserve_price < listing.auction_start_price):
        errors["auction_reserve_price"] = "Резервная цена не может быть ниже стартовой."
    if (listing.auction_buy_now_price is not None and listing.auction_start_price is not None
            and listing.auction_buy_now_price < listing.auction_start_price):
        errors["auction_buy_now_price"] = "Цена «Купить сейчас» не может быть ниже стартовой."

    methods = listing.delivery_methods or []
    if not methods:
        errors["delivery_methods"] = "Выберите хотя бы один способ передачи."
    if listing.delivery_cost is not None and Listing.DeliveryMethod.DELIVERY not in methods:
        errors["delivery_cost"] = "Стоимость доставки допустима только при выбранной доставке."

    minutes = listing.auction_auto_extend_minutes
    if minutes is None or not (1 <= minutes <= 30):
        errors["auction_auto_extend_minutes"] = "Автопродление должно быть от 1 до 30 минут."

    if listing.auction_start_mode == Listing.StartMode.SCHEDULED:
        if listing.auction_start is None:
            errors["auction_start"] = "Укажите дату начала."
        elif listing.auction_start <= now:
            errors["auction_start"] = "Начало должно быть в будущем."

    start, end = _effective_window(listing, now)
    if end is None:
        errors["auction_end"] = "Укажите дату окончания или длительность."
    elif start is not None:
        if end <= start:
            errors["auction_end"] = "Окончание должно быть позже начала."
        else:
            duration = end - start
            if duration < MIN_DURATION or duration > MAX_DURATION:
                errors["auction_end"] = "Длительность должна быть от 1 часа до 30 дней."

    return errors


def publish_draft(user, listing: Listing) -> dict:
    if listing.seller_id != user.id:
        raise DraftError({"__all__": "Недостаточно прав."}, status=403)

    # Idempotent: a lot already published is returned unchanged (no new dates).
    if listing.status in (Listing.Status.SCHEDULED, Listing.Status.ACTIVE):
        return {"listing_id": listing.pk, "status": listing.status, "redirect": _listing_detail_url(listing)}
    if listing.status != Listing.Status.DRAFT:
        raise DraftError({"__all__": "Публиковать можно только черновик."}, status=400)

    errors = check_readiness(listing)
    if errors:
        raise DraftError(errors)

    now = timezone.now()
    if listing.auction_start_mode == Listing.StartMode.NOW:
        # Use the real publication time, never the draft creation time.
        listing.auction_start = now
        if listing.auction_duration_minutes:
            listing.auction_end = now + timedelta(minutes=listing.auction_duration_minutes)
        listing.status = Listing.Status.ACTIVE
    else:
        if listing.auction_end is None and listing.auction_duration_minutes and listing.auction_start:
            listing.auction_end = listing.auction_start + timedelta(minutes=listing.auction_duration_minutes)
        listing.status = Listing.Status.SCHEDULED
    listing.is_active = True

    try:
        listing.save()
    except ValidationError as exc:
        raise DraftError(_model_errors(exc))

    # current_price stays NULL until the first bid (clean() may have set it).
    Listing.objects.filter(pk=listing.pk).update(current_price=None)
    listing.current_price = None
    return {"listing_id": listing.pk, "status": listing.status, "redirect": _listing_detail_url(listing)}


def delete_draft(user, listing: Listing) -> None:
    if listing.seller_id != user.id:
        raise DraftError({"__all__": "Недостаточно прав."}, status=403)
    if listing.status != Listing.Status.DRAFT:
        raise DraftError({"__all__": "Удалить можно только черновик."}, status=400)
    listing.delete()


# --- seller management of a published lot ------------------------------------
# Editable before the first bid (published lot). Start date/mode/duration are
# fixed at publish; the seller may still move the end date.
MANAGE_PRE_BID_FIELDS = {
    "title", "description", "category", "condition", "location",
    "delivery_methods", "delivery_cost", "delivery_note",
    "auction_end", "auction_start_price", "auction_step", "auction_reserve_price", "auction_buy_now_price",
    "auction_auto_extend", "auction_auto_extend_minutes",
    "image_order", "cover_image_id", "excluded_image_ids",
}
# Editable after the first bid: only clarifications, never the auction terms.
MANAGE_POST_BID_FIELDS = {"description", "location", "delivery_note", "delivery_cost", "delivery_methods"}


def manage_edit(user, listing_id, payload: dict) -> dict:
    """Edit a published lot. Must run inside ``transaction.atomic``."""
    listing = Listing.objects.select_for_update().filter(pk=listing_id, type=Listing.Type.AUCTION).first()
    if listing is None:
        raise DraftError({"__all__": "Лот не найден."}, status=404)
    if listing.seller_id != user.id:
        raise DraftError({"__all__": "Недостаточно прав."}, status=403)
    if listing.status not in (Listing.Status.SCHEDULED, Listing.Status.ACTIVE):
        raise DraftError({"__all__": "Изменять можно только запланированный или активный лот."}, status=400)

    has_bids = bidding.has_bids(listing)
    allowed = MANAGE_POST_BID_FIELDS if has_bids else MANAGE_PRE_BID_FIELDS

    errors: dict = {}
    for key in payload:
        if key in allowed:
            continue
        if key in MANAGE_PRE_BID_FIELDS and has_bids:
            errors[key] = "После первой ставки этот параметр нельзя изменить."
        else:
            errors[key] = "Неизвестное поле."
    if errors:
        raise DraftError(errors)

    filtered = {k: v for k, v in payload.items() if k in allowed}
    _apply_scalar_fields(listing, filtered, errors)
    if errors:
        raise DraftError(errors)

    try:
        listing.save()
    except ValidationError as exc:
        raise DraftError(_model_errors(exc))

    if not has_bids:
        _apply_image_changes(listing, filtered)
        # No bids yet — keep current_price NULL (clean() may have set it).
        Listing.objects.filter(pk=listing.pk).update(current_price=None)
        listing.current_price = None

    logger.info("auction lot edited listing=%s by=%s has_bids=%s", listing.pk, user.pk, has_bids)
    return serialize_draft_detail(listing)


def cancel_auction(user, listing_id, reason: str = "") -> dict:
    """Cancel a lot. Seller before bids; staff (admin) any time with a reason.

    Must run inside ``transaction.atomic``. Idempotent.
    """
    listing = Listing.objects.select_for_update().filter(pk=listing_id, type=Listing.Type.AUCTION).first()
    if listing is None:
        raise DraftError({"__all__": "Лот не найден."}, status=404)

    is_owner = listing.seller_id == user.id
    is_admin = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    if not (is_owner or is_admin):
        raise DraftError({"__all__": "Недостаточно прав."}, status=403)

    if listing.status == Listing.Status.CANCELLED:
        return _cancel_response(listing)  # idempotent
    if listing.status == Listing.Status.COMPLETED:
        raise DraftError({"__all__": "Завершённый аукцион нельзя отменить."}, status=400)

    has_bids = bidding.has_bids(listing)
    reason = (reason or "").strip()
    admin_cancel = False
    if has_bids:
        if not is_admin:
            raise DraftError({"__all__": "После первой ставки отменить аукцион может только администратор."}, status=400)
        if not reason:
            raise DraftError({"reason": "Для административной отмены укажите причину."})
        admin_cancel = True

    now = timezone.now()
    Listing.objects.filter(pk=listing.pk).update(
        status=Listing.Status.CANCELLED, is_active=False, auction_result=Listing.AuctionResult.CANCELLED,
        cancelled_at=now, cancellation_reason=reason, cancelled_by=user, is_admin_cancelled=admin_cancel,
        winner=None, winning_bid=None,
    )
    listing.refresh_from_db()
    logger.info("auction cancelled listing=%s by=%s admin=%s reason=%r", listing.pk, user.pk, admin_cancel, reason)
    return _cancel_response(listing)


def _cancel_response(listing: Listing) -> dict:
    return {"ok": True, "listing_id": listing.pk, "status": listing.status, "redirect": _listing_detail_url(listing)}


def _copy_listing_images(new_listing: Listing, old_listing: Listing) -> None:
    """Clone a lot's own ListingImages (files + order + cover + source link)."""
    for old in ListingImage.objects.filter(listing=old_listing).order_by("display_order", "id"):
        clone = ListingImage(listing=new_listing, source_image=old.source_image,
                             display_order=old.display_order, is_cover=old.is_cover)
        if old.image:
            old.image.open("rb")
            try:
                content = old.image.read()
            finally:
                old.image.close()
            name = os.path.basename(old.image.name) or f"image-{old.id}.jpg"
            clone.image.save(name, ContentFile(content), save=False)
        clone.save()
    _ensure_single_cover(new_listing)


def relist(user, listing_id) -> dict:
    """Create a fresh draft from a finished/cancelled lot. Atomic (caller wraps).

    Carries over the item data and images but never the bids, winner,
    current price or result. The original lot is left untouched.
    """
    listing = Listing.objects.select_for_update().filter(pk=listing_id, type=Listing.Type.AUCTION).first()
    if listing is None:
        raise DraftError({"__all__": "Лот не найден."}, status=404)
    if listing.seller_id != user.id:
        raise DraftError({"__all__": "Недостаточно прав."}, status=403)
    if listing.status not in (Listing.Status.COMPLETED, Listing.Status.CANCELLED):
        raise DraftError({"__all__": "Повторно выставить можно только завершённый или отменённый лот."}, status=400)

    card = listing.item
    # Never create a second in-progress auction for the same card.
    blocking = (
        _published_lot(card, user)
        or Listing.objects.filter(item=card, seller=user, type=Listing.Type.AUCTION, status=Listing.Status.DRAFT)
        .order_by("-created_at").first()
    )
    if blocking is not None:
        return {"ok": True, "listing_id": blocking.pk, "redirect": _listing_detail_url(blocking),
                "manage": blocking.status == Listing.Status.DRAFT, "reused": True}

    draft = Listing(
        item=card, seller=user, type=Listing.Type.AUCTION, status=Listing.Status.DRAFT, is_active=False,
        title=listing.title, description=listing.description, category=listing.category,
        item_condition=listing.item_condition, location=listing.location,
        delivery_methods=list(listing.delivery_methods or []), delivery_cost=listing.delivery_cost,
        delivery_note=listing.delivery_note, auction_start_price=listing.auction_start_price,
        auction_step=listing.auction_step, auction_reserve_price=listing.auction_reserve_price,
        auction_buy_now_price=listing.auction_buy_now_price,
        auction_auto_extend=listing.auction_auto_extend,
        auction_auto_extend_minutes=listing.auction_auto_extend_minutes,
        auction_start_mode=listing.auction_start_mode,
        # Dates, current_price, winner and result are intentionally NOT carried over.
    )
    draft.save()
    # clean() may have copied the start price into current_price — keep it NULL.
    Listing.objects.filter(pk=draft.pk).update(current_price=None)
    draft.current_price = None
    _copy_listing_images(draft, listing)
    logger.info("auction relisted listing=%s -> draft=%s", listing.pk, draft.pk)
    return {"ok": True, "listing_id": draft.pk, "redirect": _listing_detail_url(draft), "manage": True, "reused": False}
