"""Implements the Django views that replace the former Java market controllers."""
from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Iterable

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, F, Q, TextField
from django.db.models.functions import Cast, Coalesce
from django.db.utils import DatabaseError
import json

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from core.utils import moderation

from .models import AuctionBid, Listing, ListingImage, Message
from .services import bidding

TAB_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    (Listing.Type.AUCTION, "Аукцион", "market_auction"),
    (Listing.Type.SHOP, "Магазин", "market_shop"),
    (Listing.Type.FREE, "Даром", "market_free"),
    (Listing.Type.WANTED, "Спрос", "market_wanted"),
    (Listing.Type.SWAP, "Обмен", "market_swap"),
)

DEFAULT_PAGE_SIZE = 12
MARKET_ERROR_MESSAGE = "Не удалось загрузить объявления. Проверьте подключение к базе данных и выполненные миграции."

CATEGORY_LABELS = {value: label for value, label in Listing.Category.choices}
CATEGORY_VALUES = set(CATEGORY_LABELS.keys())
CATEGORY_LIST = [
    {"value": value, "label": label, "slug": value}
    for value, label in Listing.Category.choices
]


def _parse_decimal(raw: str | None) -> Decimal | None:
    """Parse a money GET value, tolerating spaces and a decimal comma."""
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).replace(" ", "").replace("\xa0", "").replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return value if value >= 0 else None


def _parse_int(raw: str | None) -> int | None:
    """Parse a non-negative integer GET value, ignoring junk."""
    if raw in (None, ""):
        return None
    try:
        value = int(str(raw).strip())
    except (ValueError, TypeError):
        return None
    return value if value >= 0 else None


def _parse_day(raw: str | None, *, end: bool = False):
    """Parse a ``<input type=date>`` (YYYY-MM-DD) into an aware datetime.

    ``end`` returns the last microsecond of the day so a "to" bound is
    inclusive; junk input yields ``None`` (the filter is simply skipped).
    """
    if not raw:
        return None
    try:
        day = datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    moment = datetime.combine(day, time.max if end else time.min)
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, timezone.get_current_timezone())
    return moment


def _checkbox_on(raw: str | None) -> bool:
    return str(raw).lower() in ("1", "on", "true", "yes")


def _ru_plural(n: int, forms: tuple[str, str, str]) -> str:
    """Russian pluralization: forms = (one, few, many)."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def _seo_context(
    request: HttpRequest,
    *,
    title: str,
    description: str,
    indexable: bool,
    canonical_path: str | None = None,
) -> dict[str, str]:
    path = canonical_path or request.path
    return {
        "seo_title": title,
        "seo_description": description,
        "seo_robots": "index,follow" if indexable else "noindex,nofollow",
        "canonical_url": request.build_absolute_uri(path),
    }


def market_root(request: HttpRequest) -> HttpResponse:
    """Market hub. Auction is the only open direction; the rest are «Скоро»."""
    soon_directions = [
        {"label": "Продажа по фиксированной цене", "note": "Продавайте вещи по заданной цене."},
        {"label": "Обмен", "note": "Меняйтесь вещами с другими пользователями."},
        {"label": "Бесплатная передача", "note": "Отдавайте вещи даром."},
    ]
    context = {
        "page_title": "Маркет",
        "active_section": "market",
        "show_search": True,
        "search_action": reverse("market_auction"),
        "tabs": list(_get_tabs("")),
        "auction_url": reverse("market_auction"),
        "create_url": reverse("market_auction_create"),
        "soon_directions": soon_directions,
        **_seo_context(
            request,
            title="Маркет | СКлад",
            description="Маркет СКлада: аукционные торги вещами из вашего архива.",
            indexable=True,
            canonical_path=reverse("market_root"),
        ),
    }
    return render(request, "market/hub.html", context)


def _get_tabs(active_type: str) -> Iterable[dict[str, str]]:
    # Only Auction is currently open; the other directions render as disabled
    # «Скоро» tabs (not working links).
    for type_code, label, url_name in TAB_DEFINITIONS:
        yield {
            "type": type_code,
            "label": label,
            "url_name": url_name,
            "active": type_code == active_type,
            "enabled": type_code == Listing.Type.AUCTION,
        }


def _build_category_links(
    request: HttpRequest,
    *,
    base_url: str,
    current_category: str,
    use_path_category: bool = False,
) -> list[dict[str, str]]:
    params = request.GET.copy()
    for key in ("page",):
        params.pop(key, None)
    if use_path_category:
        params.pop("category", None)

    def make_url(value: str | None) -> str:
        query = params.copy()
        if use_path_category:
            base_path = reverse("market_auction") if not value else reverse("market_auction_by_cat", args=[value])
        else:
            base_path = base_url
            if value:
                query["category"] = value
            else:
                query.pop("category", None)
        query_string = query.urlencode()
        return f"{base_path}?{query_string}" if query_string else base_path

    links: list[dict[str, str]] = [
        {
            "label": "Все",
            "value": "",
            "slug": "",
            "url": make_url(None),
            "active": not current_category,
        }
    ]

    for item in CATEGORY_LIST:
        value = item["value"]
        links.append(
            {
                "label": item["label"],
                "value": value,
                "slug": item["slug"],
                "url": make_url(value),
                "active": current_category == value,
            }
        )

    return links


def _apply_search(qs, query: str):
    if not query:
        return qs
    query = query.strip()
    if not query:
        return qs
    return qs.filter(
        Q(title__icontains=query)
        | Q(description__icontains=query)
        | Q(item__title__icontains=query)
        | Q(item__rubric__name__icontains=query)
    )


def _apply_ordering(qs, order: str, allow_price: bool = True):
    if order == "price" and allow_price:
        return qs.order_by(F("price").asc(nulls_last=True), "-created_at")
    if order == "-price" and allow_price:
        return qs.order_by(F("price").desc(nulls_last=True), "-created_at")
    if order == "date":
        return qs.order_by("created_at")
    if order == "-date":
        return qs.order_by("-created_at")
    # default ordering is defined on the model
    return qs


def _paginate_queryset(request: HttpRequest, qs):
    try:
        paginator = Paginator(qs, DEFAULT_PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))
    except DatabaseError:
        paginator = Paginator([], DEFAULT_PAGE_SIZE)
        page_obj = paginator.get_page(1)
        return paginator, page_obj, MARKET_ERROR_MESSAGE
    return paginator, page_obj, ""


def _build_list_context(
    request: HttpRequest,
    listing_type: str,
    *,
    base_url: str,
    category_override: str | None = None,
    use_path_category: bool = False,
):
    qs = Listing.objects.filter(
        type=listing_type, is_active=True, is_invalidated=False, is_unpublished=False,
    ).select_related(
        "item", "item__rubric", "item__rubric__profile", "seller"
    ).prefetch_related("item__images")

    category = category_override if category_override is not None else request.GET.get("category", "")
    if category not in CATEGORY_VALUES:
        category = ""
    if category:
        qs = qs.filter(category=category)

    query = request.GET.get("q", "")
    order = request.GET.get("order", "-date")
    qs = _apply_search(qs, query)
    allow_price = listing_type in {Listing.Type.SHOP, Listing.Type.WANTED}
    qs = _apply_ordering(qs, order, allow_price=allow_price)

    paginator, page_obj, market_error = _paginate_queryset(request, qs)

    params = request.GET.copy()
    params.pop("page", None)
    query_string = params.urlencode()

    return {
        "tabs": list(_get_tabs(listing_type)),
        "page_obj": page_obj,
        "paginator": paginator,
        "query": query,
        "order": order,
        "active_type": listing_type,
        "now": timezone.now(),
        "active_section": "market",
        "allow_price_order": allow_price,
        "categories": _build_category_links(
            request,
            base_url=base_url,
            current_category=category,
            use_path_category=use_path_category,
        ),
        "active_category": category,
        "active_category_label": CATEGORY_LABELS.get(category, ""),
        "query_string": query_string,
        "market_error": market_error,
    }


def market_shop(request: HttpRequest) -> HttpResponse:
    context = _build_list_context(
        request,
        Listing.Type.SHOP,
        base_url=reverse("market_shop"),
    )
    seo_context = _seo_context(
        request,
        title="Маркет - магазин объявлений | СКлад",
        description="Публичные объявления о продаже вещей и коллекций в маркете СКлада.",
        indexable=True,
        canonical_path=reverse("market_shop"),
    )
    return render(request, "market/shop.html", {**context, "page_title": "Маркет — Магазин", **seo_context})


def market_free(request: HttpRequest) -> HttpResponse:
    context = _build_list_context(
        request,
        Listing.Type.FREE,
        base_url=reverse("market_free"),
    )
    seo_context = _seo_context(
        request,
        title="Маркет - даром | СКлад",
        description="Публичные объявления с бесплатной отдачей вещей в маркете СКлада.",
        indexable=True,
        canonical_path=reverse("market_free"),
    )
    return render(request, "market/free.html", {**context, "page_title": "Маркет — Даром", **seo_context})


def market_wanted(request: HttpRequest) -> HttpResponse:
    context = _build_list_context(
        request,
        Listing.Type.WANTED,
        base_url=reverse("market_wanted"),
    )
    seo_context = _seo_context(
        request,
        title="Маркет - спрос | СКлад",
        description="Публичные объявления о поиске и покупке вещей в маркете СКлада.",
        indexable=True,
        canonical_path=reverse("market_wanted"),
    )
    return render(request, "market/wanted.html", {**context, "page_title": "Маркет — Спрос", **seo_context})


def market_swap(request: HttpRequest) -> HttpResponse:
    context = _build_list_context(
        request,
        Listing.Type.SWAP,
        base_url=reverse("market_swap"),
    )
    seo_context = _seo_context(
        request,
        title="Маркет - обмен | СКлад",
        description="Публичные объявления об обмене вещами в маркете СКлада.",
        indexable=True,
        canonical_path=reverse("market_swap"),
    )
    return render(request, "market/swap.html", {**context, "page_title": "Маркет — Обмен", **seo_context})


AUCTION_ORDER_VALUES = {"-date", "date", "ending", "price", "-price", "bids"}


def _apply_auction_ordering(qs, order: str):
    """Ordering tailored to auctions: ending time, effective price, bids, date.

    ``eff_price`` (current price, falling back to the start price) is annotated
    on the queryset before this is called.
    """
    if order == "ending":
        return qs.order_by(F("auction_end").asc(nulls_last=True), "-created_at")
    if order == "price":
        return qs.order_by(F("eff_price").asc(nulls_last=True), "-created_at")
    if order == "-price":
        return qs.order_by(F("eff_price").desc(nulls_last=True), "-created_at")
    if order == "bids":
        return qs.order_by("-num_bids", "-created_at")
    if order == "date":
        return qs.order_by("created_at")
    return qs.order_by("-created_at")


def market_auction(request: HttpRequest, category_slug: str | None = None) -> HttpResponse:
    category = category_slug or request.GET.get("category", "")
    if category not in CATEGORY_VALUES:
        category = ""

    # Finalize lots whose time has elapsed so the board shows correct results.
    finalize_now = timezone.now()
    for ended in Listing.objects.filter(
        type=Listing.Type.AUCTION, status=Listing.Status.ACTIVE, auction_end__lte=finalize_now
    ).values_list("pk", flat=True)[:100]:
        bidding.finalize_auction(ended)

    # Drafts (private) and cancelled lots never appear on the public board.
    # ``num_bids`` uses distinct=True so it stays correct even when later filters
    # (e.g. «только с фото») add one-to-many joins that would otherwise multiply
    # rows. ``eff_price`` is the current price, falling back to the start price.
    qs = (
        Listing.objects.filter(type=Listing.Type.AUCTION)
        .exclude(status__in=[Listing.Status.DRAFT, Listing.Status.CANCELLED])
        .select_related("item", "seller")
        .prefetch_related("images", "item__images")
        .annotate(
            num_bids=Count("auction_bids", distinct=True),
            eff_price=Coalesce("current_price", "auction_start_price"),
        )
    )

    if category:
        qs = qs.filter(category=category)

    condition_values = {c.value for c in Listing.Condition}
    condition = request.GET.get("condition", "")
    if condition in condition_values:
        qs = qs.filter(item_condition=condition)
    else:
        condition = ""

    query = request.GET.get("q", "")
    qs = _apply_search(qs, query)

    state = request.GET.get("state")
    if state == "active":
        qs = qs.filter(status=Listing.Status.ACTIVE)
    elif state in ("scheduled", "upcoming"):
        state = "scheduled"
        qs = qs.filter(status=Listing.Status.SCHEDULED)
    elif state == "ended":
        qs = qs.filter(status=Listing.Status.COMPLETED)
    else:
        state = ""
        # default board: hide finished lots
        qs = qs.exclude(status=Listing.Status.COMPLETED)

    # --- Delivery method ----------------------------------------------------
    delivery_values = {d.value for d in Listing.DeliveryMethod}
    delivery = request.GET.get("delivery", "")
    if delivery in delivery_values:
        # ``__contains`` is the right jsonb lookup on PostgreSQL (production);
        # backends without JSON contains (e.g. SQLite) fall back to a quoted
        # substring match on the serialized array so the filter stays portable.
        if connection.features.supports_json_field_contains:
            qs = qs.filter(delivery_methods__contains=[delivery])
        else:
            qs = qs.annotate(_dm_text=Cast("delivery_methods", TextField())).filter(
                _dm_text__icontains='"%s"' % delivery
            )
    else:
        delivery = ""

    # --- City ----------------------------------------------------------------
    city = (request.GET.get("city", "") or "").strip()
    if city:
        qs = qs.filter(location__icontains=city)

    # --- Date ranges (start / end) ------------------------------------------
    start_from_raw = request.GET.get("start_from", "")
    start_to_raw = request.GET.get("start_to", "")
    end_from_raw = request.GET.get("end_from", "")
    end_to_raw = request.GET.get("end_to", "")
    start_from = _parse_day(start_from_raw)
    start_to = _parse_day(start_to_raw, end=True)
    end_from = _parse_day(end_from_raw)
    end_to = _parse_day(end_to_raw, end=True)
    if start_from:
        qs = qs.filter(auction_start__gte=start_from)
    if start_to:
        qs = qs.filter(auction_start__lte=start_to)
    if end_from:
        qs = qs.filter(auction_end__gte=end_from)
    if end_to:
        qs = qs.filter(auction_end__lte=end_to)

    # --- Price range (effective price) --------------------------------------
    price_min_raw = request.GET.get("price_min", "")
    price_max_raw = request.GET.get("price_max", "")
    price_min = _parse_decimal(price_min_raw)
    price_max = _parse_decimal(price_max_raw)
    if price_min is not None:
        qs = qs.filter(eff_price__gte=price_min)
    if price_max is not None:
        qs = qs.filter(eff_price__lte=price_max)

    # --- Bid count range -----------------------------------------------------
    bids_min_raw = request.GET.get("bids_min", "")
    bids_max_raw = request.GET.get("bids_max", "")
    bids_min = _parse_int(bids_min_raw)
    bids_max = _parse_int(bids_max_raw)
    if bids_min is not None:
        qs = qs.filter(num_bids__gte=bids_min)
    if bids_max is not None:
        qs = qs.filter(num_bids__lte=bids_max)

    # --- Boolean extras ------------------------------------------------------
    only_photo = _checkbox_on(request.GET.get("photo"))
    only_reserve = _checkbox_on(request.GET.get("reserve"))
    reserve_reached = _checkbox_on(request.GET.get("reserve_reached"))
    only_no_bids = _checkbox_on(request.GET.get("no_bids"))
    only_active = _checkbox_on(request.GET.get("only_active"))
    if only_photo:
        qs = qs.filter(Q(images__isnull=False) | Q(item__images__isnull=False)).distinct()
    if only_reserve:
        qs = qs.filter(auction_reserve_price__isnull=False)
    if reserve_reached:
        qs = qs.filter(
            auction_reserve_price__isnull=False,
            current_price__isnull=False,
            current_price__gte=F("auction_reserve_price"),
        )
    if only_no_bids:
        qs = qs.filter(num_bids=0)
    if only_active:
        qs = qs.filter(status=Listing.Status.ACTIVE)

    order = request.GET.get("order", "-date")
    if order not in AUCTION_ORDER_VALUES:
        order = "-date"
    qs = _apply_auction_ordering(qs, order)

    paginator, page_obj, market_error = _paginate_queryset(request, qs)

    # Attach display-only fields for the card (cover, condition, reserve, status).
    condition_labels = dict(Listing.Condition.choices)
    for listing in page_obj.object_list:
        imgs = list(listing.images.all())
        cover = next((i for i in imgs if i.is_cover), imgs[0] if imgs else None)
        cover_url = cover.image.url if cover and cover.image else ""
        if not cover_url:
            # Fall back to the source ArchiveFile image when the lot has none.
            item_imgs = list(listing.item.images.all())
            if item_imgs and item_imgs[0].image:
                cover_url = item_imgs[0].image.url
        listing.cover_url = cover_url
        listing.condition_label = condition_labels.get(listing.item_condition, "")
        listing.city = listing.location or ""
        listing.status_text = AUCTION_STATUS_TEXT.get(listing.status, listing.get_status_display())
        if listing.auction_reserve_price is None:
            listing.reserve_label = ""
        elif listing.current_price is not None and listing.current_price >= listing.auction_reserve_price:
            listing.reserve_label = "Резерв достигнут"
        else:
            listing.reserve_label = "Резерв не достигнут"

    params = request.GET.copy()
    params.pop("page", None)
    query_string = params.urlencode()

    found_count = paginator.count
    # Filters carried into the topbar search form as hidden inputs (so a search
    # keeps the active filters), and into pagination via ``query_string``.
    preserved = request.GET.copy()
    preserved.pop("page", None)
    preserved.pop("q", None)

    context = {
        "tabs": list(_get_tabs(Listing.Type.AUCTION)),
        "page_obj": page_obj,
        "paginator": paginator,
        "query": query,
        "order": order,
        "state": state,
        "active_type": Listing.Type.AUCTION,
        "now": timezone.now(),
        "active_section": "market",
        "allow_price_order": False,
        # --- Filter form data ------------------------------------------------
        "category_options": CATEGORY_LIST,
        "active_category": category,
        "active_category_label": CATEGORY_LABELS.get(category, ""),
        "conditions": [{"value": v, "label": l} for v, l in Listing.Condition.choices],
        "active_condition": condition,
        "delivery_options": [{"value": v, "label": l} for v, l in Listing.DeliveryMethod.choices],
        "active_delivery": delivery,
        "city": city,
        "f_start_from": start_from_raw,
        "f_start_to": start_to_raw,
        "f_end_from": end_from_raw,
        "f_end_to": end_to_raw,
        "f_price_min": price_min_raw,
        "f_price_max": price_max_raw,
        "f_bids_min": bids_min_raw,
        "f_bids_max": bids_max_raw,
        "f_only_photo": only_photo,
        "f_only_reserve": only_reserve,
        "f_reserve_reached": reserve_reached,
        "f_only_no_bids": only_no_bids,
        "f_only_active": only_active,
        "found_count": found_count,
        "found_word": _ru_plural(found_count, ("объявление", "объявления", "объявлений")),
        "reset_url": reverse("market_auction"),
        "preserved_params": preserved,
        "create_url": reverse("market_auction_create"),
        "query_string": query_string,
        "market_error": market_error,
    }
    canonical_path = reverse("market_auction") if not category else reverse("market_auction_by_cat", args=[category])
    seo_context = _seo_context(
        request,
        title="Маркет - аукцион | СКлад",
        description="Публичные аукционные объявления в маркете СКлада.",
        indexable=True,
        canonical_path=canonical_path,
    )
    return render(request, "market/auction.html", {**context, "page_title": "Маркет — Аукцион", **seo_context})


AUCTION_CHARACTERISTIC_FIELDS = (
    ("category", "Категория товара"),
    ("condition", "Состояние"),
    ("completeness", "Комплектность"),
    ("location", "Местонахождение"),
    ("handover", "Способ передачи"),
    ("extra", "Дополнительная информация"),
)


@login_required
@ensure_csrf_cookie
def market_auction_create(request: HttpRequest) -> HttpResponse:
    """Render the «Создать лот» flow (archive card or new card)."""
    from auction import services
    from auction.constants import AUCTION_FIELD_SCHEMA

    cards = [services.serialize_eligible_card(c) for c in services.eligible_cards_for_user(request.user)]
    context = {
        "tabs": list(_get_tabs(Listing.Type.AUCTION)),
        "page_title": "Аукцион — Создать лот",
        "active_section": "market",
        "active_type": Listing.Type.AUCTION,
        "show_search": False,
        "eligible_cards": cards,
        "field_schema": AUCTION_FIELD_SCHEMA,
        "categories_list": CATEGORY_LIST,
        "conditions": [{"value": v, "label": l} for v, l in Listing.Condition.choices],
        "back_url": reverse("market_auction"),
        **_seo_context(
            request,
            title="Создать лот — Аукцион | СКлад",
            description="Создание аукционного лота из карточки архива или новой карточки.",
            indexable=False,
            canonical_path=reverse("market_auction_create"),
        ),
    }
    return render(request, "market/auction_create.html", context)


def _auction_characteristics(item, lot=None) -> list[dict[str, str]]:
    from auction.constants import CONDITION_LABELS

    # Prefer the frozen lot snapshot (card data + auction-only overrides) so the
    # listing stays independent of later card edits and shows auction attributes.
    data = dict(item.data) if isinstance(item.data, dict) else {}
    if lot is not None and isinstance(lot.snapshot, dict):
        snap = lot.snapshot.get('data')
        if isinstance(snap, dict):
            data.update(snap)
    rows: list[dict[str, str]] = []
    for key, label in AUCTION_CHARACTERISTIC_FIELDS:
        value = data.get(key)
        if not value:
            continue
        if key == "condition":
            value = CONDITION_LABELS.get(value, value)
        rows.append({"label": label, "value": value})
    return rows


AUCTION_STATUS_TEXT = {
    Listing.Status.SCHEDULED: "Аукцион начнётся",
    Listing.Status.ACTIVE: "Аукцион идёт",
    Listing.Status.COMPLETED: "Аукцион завершён",
    Listing.Status.CANCELLED: "Аукцион отменён",
    Listing.Status.DRAFT: "Черновик",
}


def _auction_completed_outcome(listing: Listing, state: dict) -> str:
    if not state["has_bids"]:
        return "Нет ставок"
    if listing.auction_reserve_price is not None and state["reserve_status"] == "not_reached":
        return "Резерв не достигнут"
    return "Лот продан"


@ensure_csrf_cookie
def market_auction_detail(request: HttpRequest, listing_id: int) -> HttpResponse:
    """Public auction lot page. Drafts are visible to their owner only."""
    listing = (
        Listing.objects.select_related("item", "item__rubric", "seller")
        .prefetch_related("images")
        .filter(pk=listing_id, type=Listing.Type.AUCTION)
        .first()
    )
    if listing is None:
        raise Http404("Лот не найден")
    is_owner = request.user.is_authenticated and request.user.id == listing.seller_id
    if (listing.is_invalidated or listing.is_unpublished) and not is_owner:
        raise Http404("Listing not found")
    if listing.status == Listing.Status.DRAFT and not is_owner:
        raise Http404("Лот не найден")

    bidding.finalize_auction(listing)
    listing.refresh_from_db()
    state = bidding.serialize_state(request.user, listing)
    all_bids = bidding.serialize_bids(listing)
    has_bids = state["has_bids"]
    is_admin = request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)

    # Gallery: cover first, then the rest in display order, drop empty files.
    images = list(listing.images.all())
    cover = next((img for img in images if img.is_cover), images[0] if images else None)
    cover_pk = cover.pk if cover else None
    ordered = ([cover] + [i for i in images if i.pk != cover_pk]) if cover else images
    gallery = [{"url": i.image.url, "is_cover": i.is_cover} for i in ordered if i.image]

    delivery_labels = dict(Listing.DeliveryMethod.choices)
    selected_methods = listing.delivery_methods or []
    delivery_methods = [delivery_labels.get(m, m) for m in selected_methods]
    show_delivery = Listing.DeliveryMethod.DELIVERY in selected_methods

    condition_labels = dict(Listing.Condition.choices)
    condition_text = condition_labels.get(listing.item_condition, "") if listing.item_condition else ""

    characteristics = []
    if condition_text:
        characteristics.append({"label": "Состояние", "value": condition_text})
    characteristics.append({"label": "Категория", "value": listing.get_category_display()})
    if listing.location:
        characteristics.append({"label": "Местоположение", "value": listing.location})
    if delivery_methods:
        characteristics.append({"label": "Способы получения", "value": ", ".join(delivery_methods)})

    is_finished = listing.status in (Listing.Status.COMPLETED, Listing.Status.CANCELLED)
    completed_outcome = _auction_completed_outcome(listing, state) if listing.status == Listing.Status.COMPLETED else ""

    # --- Seller management + result -----------------------------------------
    is_live = listing.status in (Listing.Status.SCHEDULED, Listing.Status.ACTIVE)
    can_edit = is_owner and is_live
    can_cancel = is_owner and is_live and not has_bids
    can_admin_cancel = is_admin and is_live and has_bids
    can_relist = is_owner and listing.status in (Listing.Status.COMPLETED, Listing.Status.CANCELLED)
    can_buy_now = (
        request.user.is_authenticated
        and not is_owner
        and listing.status == Listing.Status.ACTIVE
        and listing.auction_buy_now_price is not None
        and listing.auction_buy_now_price >= bidding.current_price_base(listing)
    )

    result_text_map = {
        Listing.AuctionResult.NO_BIDS: "Аукцион завершён без ставок",
        Listing.AuctionResult.RESERVE_NOT_REACHED: "Аукцион завершён. Резервная цена не достигнута",
        Listing.AuctionResult.SOLD: "Аукцион завершён",
        Listing.AuctionResult.CANCELLED: "Аукцион отменён",
    }
    result_text = result_text_map.get(listing.auction_result, "") if is_finished else ""
    is_sold = listing.status == Listing.Status.COMPLETED and listing.auction_result == Listing.AuctionResult.SOLD
    final_price = None
    winner_public = ""
    winner_full = ""
    is_winner = False
    if is_sold and listing.winner_id:
        final_price = listing.current_price
        winner_public = bidding.mask_username(listing.winner.get_username())
        is_winner = request.user.is_authenticated and listing.winner_id == request.user.id
        if is_owner:
            winner_full = listing.winner.get_username()

    lot_url = reverse("market_auction_detail", args=[listing.pk])
    config = {
        "endpoints": {
            "state": reverse("market_api_auction_state", args=[listing.pk]),
            "bid": reverse("market_api_auction_bid", args=[listing.pk]),
            "buy_now": reverse("market_api_auction_buy_now", args=[listing.pk]),
            "bids": reverse("market_api_auction_bids", args=[listing.pk]),
            "detail": reverse("market_api_auction_draft_manage", args=[listing.pk]),
            "manage": reverse("market_api_auction_manage", args=[listing.pk]),
            "cancel": reverse("market_api_auction_cancel", args=[listing.pk]),
            "relist": reverse("market_api_auction_relist", args=[listing.pk]),
        },
        "state": state,
        "step": str(listing.auction_step) if listing.auction_step is not None else None,
        "is_owner": is_owner,
        "is_admin": bool(is_admin),
        "has_bids": has_bids,
        "is_authenticated": bool(request.user.is_authenticated),
        "lot_url": lot_url,
    }

    context = {
        "listing": listing,
        "is_owner": is_owner,
        "state": state,
        "status_text": AUCTION_STATUS_TEXT.get(listing.status, listing.get_status_display()),
        "is_finished": is_finished,
        "completed_outcome": completed_outcome,
        "condition_text": condition_text,
        "gallery": gallery,
        "delivery_methods": delivery_methods,
        "show_delivery": show_delivery,
        "characteristics": characteristics,
        "initial_bids": all_bids[:5],
        "has_more_bids": len(all_bids) > 5,
        "seller_name": listing.seller.get_username(),
        "login_url": "/?next=" + lot_url,
        "has_bids": has_bids,
        "bid_count": state["bid_count"],
        "can_edit": can_edit,
        "can_cancel": can_cancel,
        "can_admin_cancel": can_admin_cancel,
        "can_relist": can_relist,
        "can_buy_now": can_buy_now,
        "result_text": result_text,
        "is_sold": is_sold,
        "final_price": final_price,
        "winner_public": winner_public,
        "winner_full": winner_full,
        "is_winner": is_winner,
        "cancellation_reason": listing.cancellation_reason if listing.status == Listing.Status.CANCELLED else "",
        "tabs": list(_get_tabs(Listing.Type.AUCTION)),
        "active_section": "market",
        "back_url": reverse("market_auction"),
        "show_search": False,
        "now": timezone.now(),
        "auction_config_json": json.dumps(config),
        "page_title": f"Аукцион — {listing.title or listing.item.title}",
        **_seo_context(
            request,
            title=f"{listing.title or listing.item.title} — Аукцион | СКлад",
            description=(listing.description or "Аукционный лот в маркете СКлада.")[:160],
            indexable=listing.status in (Listing.Status.ACTIVE, Listing.Status.SCHEDULED, Listing.Status.COMPLETED),
            canonical_path=lot_url,
        ),
    }
    return render(request, "market/auction_detail.html", context)


@ensure_csrf_cookie
def market_listing_detail(request: HttpRequest, pk: int) -> HttpResponse:
    listing = get_object_or_404(
        Listing.objects.select_related("item", "item__rubric", "item__rubric__profile", "seller", "auction_lot")
        .prefetch_related("item__images", "bids__bidder"),
        pk=pk,
    )
    tab_url_map = {
        Listing.Type.SHOP: "market_shop",
        Listing.Type.AUCTION: "market_auction",
        Listing.Type.FREE: "market_free",
        Listing.Type.WANTED: "market_wanted",
        Listing.Type.SWAP: "market_swap",
    }
    back_url = reverse(tab_url_map.get(listing.type, "market_shop"))

    lot = getattr(listing, "auction_lot", None)
    is_owner = request.user.is_authenticated and request.user.id == listing.seller_id
    if (listing.is_invalidated or listing.is_unpublished) and not is_owner:
        raise Http404("Listing not found")
    auction_extra: dict = {}
    if listing.type == Listing.Type.AUCTION and lot is not None:
        from auction import services
        from auction.models import AuctionLot

        history = services.bid_history(lot)
        has_bids = bool(history)
        auction_extra = {
            "lot": lot,
            "characteristics": _auction_characteristics(listing.item, lot),
            "bid_history": history,
            "bid_count": len(history),
            "min_bid": lot.get_minimum_bid_amount(),
            "can_bid": (
                request.user.is_authenticated and not is_owner
                and lot.status == AuctionLot.Status.ACTIVE
            ),
            "can_buy_now": (
                request.user.is_authenticated and not is_owner
                and lot.buy_now_price is not None
                and lot.status == AuctionLot.Status.ACTIVE
            ),
            "can_edit": is_owner and not has_bids and lot.status in (
                AuctionLot.Status.DRAFT, AuctionLot.Status.SCHEDULED, AuctionLot.Status.ACTIVE,
            ),
        }

    return render(
        request,
        "market/detail.html",
        {
            "listing": listing,
            "is_owner": is_owner,
            "tabs": list(_get_tabs(listing.type)),
            "page_title": f"Маркет — {listing.get_type_display()}",
            "now": timezone.now(),
            "active_section": "market",
            "back_url": back_url,
            **auction_extra,
            **_seo_context(
                request,
                title=f"{listing.title or listing.item.title} | СКлад",
                description=(listing.description or f"Публичное объявление {listing.get_type_display()} в СКлад.")[:160],
                indexable=listing.is_active,
                canonical_path=reverse("market_listing_detail", args=[listing.pk]),
            ),
        },
    )


@login_required
def market_messages(request: HttpRequest) -> HttpResponse:
    User = get_user_model()
    errors: dict[str, str] = {}
    sent = False

    recipient_id = request.POST.get("recipient") or request.GET.get("to")
    listing_id = request.POST.get("listing_id") or request.GET.get("item")

    listing = None
    recipient = None

    if listing_id:
        try:
            listing = Listing.objects.select_related("seller").get(pk=listing_id)
        except (Listing.DoesNotExist, ValueError):
            errors["listing_id"] = "Объявление не найдено."
        else:
            if not recipient_id:
                recipient_id = str(listing.seller_id)

    if recipient_id:
        try:
            recipient = User.objects.get(pk=recipient_id)
        except (User.DoesNotExist, ValueError):
            errors["recipient"] = "Пользователь не найден."

    message_text = request.POST.get("message", "") if request.method == "POST" else ""

    if request.method == "POST" and not errors:
        message_text = (request.POST.get("message") or "").strip()
        if not message_text:
            errors["message"] = "Введите сообщение."
        elif recipient is None:
            errors["recipient"] = "Получатель не выбран."
        elif recipient == request.user:
            errors["recipient"] = "Нельзя отправлять сообщение самому себе."
        else:
            try:
                moderation.ensure_text_allowed(message_text, field='message')
            except ValidationError as exc:
                errors["message"] = exc.messages[0]
            else:
                Message.objects.create(
                    listing=listing,
                    sender=request.user,
                    recipient=recipient,
                    text=message_text,
                )
                sent = True
                message_text = ""

    context = {
        "recipient": recipient,
        "listing": listing,
        "errors": errors,
        "sent": sent,
        "tabs": list(_get_tabs(Listing.Type.SHOP)),
        "page_title": "Маркет — Сообщения",
        "active_section": "market",
        "show_search": False,
        "message_text": message_text,
        "recipient_id": recipient.id if recipient else (recipient_id or ""),
        "listing_id": listing.id if listing else (listing_id or ""),
        **_seo_context(
            request,
            title="Сообщения - СКлад",
            description="Личные сообщения пользователей маркета.",
            indexable=False,
            canonical_path=reverse("messages"),
        ),
    }
    return render(request, "market/messages.html", context)
