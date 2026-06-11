"""Implements the Django views that replace the former Java market controllers."""
from __future__ import annotations

from typing import Iterable

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.db.utils import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.utils import moderation

from .models import Listing, Message

TAB_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    (Listing.Type.SHOP, "Магазин", "market_shop"),
    (Listing.Type.AUCTION, "Аукцион", "market_auction"),
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
    return redirect("market_auction")


def _get_tabs(active_type: str) -> Iterable[dict[str, str]]:
    for type_code, label, url_name in TAB_DEFINITIONS:
        yield {
            "type": type_code,
            "label": label,
            "url_name": url_name,
            "active": type_code == active_type,
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
    qs = Listing.objects.filter(type=listing_type, is_active=True).select_related(
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


def market_auction(request: HttpRequest, category_slug: str | None = None) -> HttpResponse:
    category = category_slug or request.GET.get("category", "")
    if category not in CATEGORY_VALUES:
        category = ""

    qs = Listing.objects.filter(type=Listing.Type.AUCTION, is_active=True).select_related(
        "item", "item__rubric", "item__rubric__profile", "seller"
    ).prefetch_related("item__images")

    if category:
        qs = qs.filter(category=category)

    query = request.GET.get("q", "")
    qs = _apply_search(qs, query)

    state = request.GET.get("state")
    now = timezone.now()
    if state == "active":
        qs = qs.filter(auction_start__lte=now, auction_end__gt=now)
    elif state == "upcoming":
        qs = qs.filter(auction_start__gt=now)
    elif state == "ended":
        qs = qs.filter(auction_end__lte=now)

    order = request.GET.get("order", "-date")
    qs = _apply_ordering(qs, order, allow_price=False)

    paginator, page_obj, market_error = _paginate_queryset(request, qs)

    params = request.GET.copy()
    params.pop("page", None)
    query_string = params.urlencode()

    context = {
        "tabs": list(_get_tabs(Listing.Type.AUCTION)),
        "page_obj": page_obj,
        "paginator": paginator,
        "query": query,
        "order": order,
        "state": state,
        "active_type": Listing.Type.AUCTION,
        "now": now,
        "active_section": "market",
        "allow_price_order": False,
        "categories": _build_category_links(
            request,
            base_url=reverse("market_auction"),
            current_category=category,
            use_path_category=True,
        ),
        "active_category": category,
        "active_category_label": CATEGORY_LABELS.get(category, ""),
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


def market_listing_detail(request: HttpRequest, pk: int) -> HttpResponse:
    listing = get_object_or_404(
        Listing.objects.select_related("item", "item__rubric", "item__rubric__profile", "seller")
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
    return render(
        request,
        "market/detail.html",
        {
            "listing": listing,
            "tabs": list(_get_tabs(listing.type)),
            "page_title": f"Маркет — {listing.get_type_display()}",
            "now": timezone.now(),
            "active_section": "market",
            "back_url": back_url,
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
