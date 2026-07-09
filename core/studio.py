"""Hidden site editor / administrator page.

Isolated from the normal user flow. Access requires an authenticated Django
superuser. Every data-returning and data-modifying endpoint re-checks
``is_superuser`` on the server — the frontend only hides UI, it never gates
security. The admin password is never present in any template/JS; login is
validated against the stored Django password hash.
"""
from __future__ import annotations

import json
from functools import wraps

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from core.admin_access import (
    check_admin_credentials,
    configured_admin_login,
    end_admin_session,
    is_admin_session,
    is_reserved_admin_username,
    start_admin_session,
)
from core.models import NewsArticle, Profile, Review
from market.models import Listing

User = get_user_model()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _is_admin(request: HttpRequest) -> bool:
    return is_admin_session(request)


def superuser_required(view):
    """Server-side gate: reject non-superusers with 403 (never a redirect)."""

    @wraps(view)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not _is_admin(request):
            return JsonResponse({"success": False, "error": "forbidden"}, status=403)
        return view(request, *args, **kwargs)

    return wrapper


def _json_body(request: HttpRequest) -> dict:
    if "json" not in str(request.content_type or "").lower():
        return {}
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _unique_slug(title: str, explicit: str, exclude_pk=None) -> str:
    base = (explicit or "").strip() or slugify(title, allow_unicode=True) or "news"
    slug = base
    index = 2
    qs = NewsArticle.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    while qs.filter(slug=slug).exists():
        slug = f"{base}-{index}"
        index += 1
    return slug


def _news_payload(article: NewsArticle) -> dict:
    return {
        "id": article.id,
        "title": article.title,
        "slug": article.slug,
        "preview": article.preview,
        "body": article.body,
        "cover": article.cover.url if article.cover else "",
        "is_published": article.is_published,
        "publish_at": article.publish_at.isoformat(),
        "updated_at": article.updated_at.isoformat(),
    }


def _user_payload(user) -> dict:
    profile = getattr(user, "profile", None)
    return {
        "id": user.id,
        "username": user.get_username(),
        "name": (f"{user.first_name} {user.last_name}").strip(),
        "email": user.email,
        "is_superuser": user.is_superuser,
        "is_blocked": bool(profile and profile.is_blocked),
        "block_reason": (profile.block_reason if profile else "") or "",
        "blocked_at": profile.blocked_at.isoformat() if (profile and profile.blocked_at) else "",
        "date_joined": user.date_joined.isoformat() if user.date_joined else "",
    }


def _listing_payload(listing: Listing) -> dict:
    if listing.is_invalidated:
        state = "invalid"
    elif listing.is_unpublished:
        state = "unpublished"
    elif listing.status == Listing.Status.COMPLETED:
        state = "closed"
    elif listing.is_active:
        state = "active"
    else:
        state = "inactive"
    return {
        "id": listing.id,
        "title": listing.title or (listing.item.title if listing.item_id else ""),
        "type": listing.get_type_display(),
        "seller": listing.seller.get_username() if listing.seller_id else "",
        "status": listing.status,
        "state": state,
        "is_active": listing.is_active,
        "is_invalidated": listing.is_invalidated,
        "is_unpublished": listing.is_unpublished,
        "moderation_reason": listing.moderation_reason or "",
        "moderated_at": listing.moderated_at.isoformat() if listing.moderated_at else "",
        "created_at": listing.created_at.isoformat(),
    }


def _review_payload(review: Review) -> dict:
    return {
        "id": review.id,
        "author": review.user.get_username() if review.user_id else "",
        "rating": review.rating,
        "text": review.text,
        "is_hidden": review.is_hidden,
        "hidden_reason": review.hidden_reason or "",
        "created_at": review.created_at.isoformat(),
    }


# --------------------------------------------------------------------------- #
# Page + auth
# --------------------------------------------------------------------------- #
@ensure_csrf_cookie
@never_cache
def studio_page(request: HttpRequest) -> HttpResponse:
    """The hidden editor page. Renders for everyone but ships no data/secrets;
    the client shows a login form until the server confirms superuser status."""
    return render(request, "studio.html", {"studio_is_admin": _is_admin(request)})


@require_POST
def studio_login(request: HttpRequest) -> JsonResponse:
    data = _json_body(request) or request.POST
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    if not check_admin_credentials(username, password):
        return JsonResponse(
            {"success": False, "error": "Неверный логин или пароль администратора."},
            status=403,
        )
    start_admin_session(request)
    return JsonResponse({"success": True, "username": configured_admin_login()})


@require_POST
def studio_logout(request: HttpRequest) -> JsonResponse:
    end_admin_session(request)
    return JsonResponse({"success": True})


@require_GET
def studio_status(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "authenticated": _is_admin(request),
            "username": configured_admin_login() if _is_admin(request) else "",
        }
    )


# --------------------------------------------------------------------------- #
# News
# --------------------------------------------------------------------------- #
@superuser_required
@require_GET
def studio_news_list(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {"success": True, "news": [_news_payload(a) for a in NewsArticle.objects.all()]}
    )


@superuser_required
@require_POST
def studio_news_save(request: HttpRequest) -> JsonResponse:
    # Uses multipart form so an optional cover image can be uploaded.
    data = request.POST
    title = str(data.get("title") or "").strip()
    if not title:
        return JsonResponse({"success": False, "error": "Укажите заголовок новости."}, status=400)

    article_id = data.get("id")
    if article_id:
        article = NewsArticle.objects.filter(id=article_id).first()
        if not article:
            return JsonResponse({"success": False, "error": "Новость не найдена."}, status=404)
    else:
        article = NewsArticle()

    article.title = title
    article.preview = str(data.get("preview") or "")
    article.body = str(data.get("body") or "")
    article.is_published = str(data.get("is_published") or "").lower() in {"1", "true", "on", "yes"}
    publish_at = str(data.get("publish_at") or "").strip()
    if publish_at:
        parsed = parse_datetime(publish_at)
        if parsed is not None:
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            article.publish_at = parsed
    elif not article.pk:
        article.publish_at = timezone.now()
    article.slug = _unique_slug(title, str(data.get("slug") or ""), exclude_pk=article.pk)

    if str(data.get("remove_cover") or "") == "1" and article.cover:
        article.cover.delete(save=False)
        article.cover = None
    if request.FILES.get("cover"):
        article.cover = request.FILES["cover"]

    article.save()
    return JsonResponse({"success": True, "id": article.id, "article": _news_payload(article)})


@superuser_required
@require_POST
def studio_news_publish(request: HttpRequest, article_id: int) -> JsonResponse:
    article = NewsArticle.objects.filter(id=article_id).first()
    if not article:
        return JsonResponse({"success": False, "error": "Новость не найдена."}, status=404)
    article.is_published = bool(_json_body(request).get("is_published", not article.is_published))
    article.save(update_fields=["is_published", "updated_at"])
    return JsonResponse({"success": True, "is_published": article.is_published})


@superuser_required
@require_POST
def studio_news_delete(request: HttpRequest, article_id: int) -> JsonResponse:
    NewsArticle.objects.filter(id=article_id).delete()
    return JsonResponse({"success": True})


# --------------------------------------------------------------------------- #
# Users (block / unblock)
# --------------------------------------------------------------------------- #
@superuser_required
@require_GET
def studio_users_search(request: HttpRequest) -> JsonResponse:
    query = str(request.GET.get("q") or "").strip()
    users = User.objects.select_related("profile").order_by("-date_joined")
    admin_login = configured_admin_login()
    if admin_login:
        users = users.exclude(username__iexact=admin_login)
    if query:
        criteria = (
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(profile__display_name__icontains=query)
        )
        if query.isdigit():
            criteria |= Q(id=int(query))
        users = users.filter(criteria)
    return JsonResponse({"success": True, "users": [_user_payload(u) for u in users[:50]]})


@superuser_required
@require_POST
def studio_user_block(request: HttpRequest, user_id: int) -> JsonResponse:
    target = User.objects.filter(id=user_id).first()
    if not target:
        return JsonResponse({"success": False, "error": "Пользователь не найден."}, status=404)
    if target.is_superuser or is_reserved_admin_username(target.get_username()):
        return JsonResponse({"success": False, "error": "Нельзя заблокировать администратора."}, status=400)
    reason = str(_json_body(request).get("reason") or "").strip()
    profile, _ = Profile.objects.get_or_create(user=target)
    profile.is_blocked = True
    profile.block_reason = reason
    profile.blocked_at = timezone.now()
    profile.blocked_by = None
    profile.save(update_fields=["is_blocked", "block_reason", "blocked_at", "blocked_by", "updated_at"])
    return JsonResponse({"success": True, "user": _user_payload(target)})


@superuser_required
@require_POST
def studio_user_unblock(request: HttpRequest, user_id: int) -> JsonResponse:
    target = User.objects.filter(id=user_id).first()
    if not target:
        return JsonResponse({"success": False, "error": "Пользователь не найден."}, status=404)
    profile, _ = Profile.objects.get_or_create(user=target)
    profile.is_blocked = False
    profile.block_reason = ""
    profile.blocked_at = None
    profile.blocked_by = None
    profile.save(update_fields=["is_blocked", "block_reason", "blocked_at", "blocked_by", "updated_at"])
    return JsonResponse({"success": True, "user": _user_payload(target)})


# --------------------------------------------------------------------------- #
# Market / auction
# --------------------------------------------------------------------------- #
@superuser_required
@require_GET
def studio_listings(request: HttpRequest) -> JsonResponse:
    status_filter = str(request.GET.get("status") or "").strip()
    qs = Listing.objects.select_related("seller", "item").order_by("-created_at")
    if status_filter == "active":
        qs = qs.filter(is_active=True, is_invalidated=False, is_unpublished=False)
    elif status_filter == "closed":
        qs = qs.filter(status=Listing.Status.COMPLETED)
    elif status_filter == "invalid":
        qs = qs.filter(is_invalidated=True)
    elif status_filter == "unpublished":
        qs = qs.filter(is_unpublished=True)
    return JsonResponse({"success": True, "listings": [_listing_payload(l) for l in qs[:100]]})


@superuser_required
@require_POST
def studio_listing_action(request: HttpRequest, listing_id: int) -> JsonResponse:
    listing = Listing.objects.filter(id=listing_id).first()
    if not listing:
        return JsonResponse({"success": False, "error": "Товар/лот не найден."}, status=404)
    data = _json_body(request)
    action = str(data.get("action") or "").strip()
    reason = str(data.get("reason") or "").strip()
    now = timezone.now()
    fields = {"moderation_reason": reason, "moderated_at": now, "moderated_by_id": None}
    if action == "invalidate":
        fields.update(
            is_invalidated=True, is_unpublished=False, is_active=False,
            status=Listing.Status.CANCELLED, is_admin_cancelled=True,
            cancellation_reason=reason, cancelled_at=now, cancelled_by_id=None,
        )
    elif action == "close":
        fields.update(is_active=False, status=Listing.Status.COMPLETED, completed_at=now)
    elif action == "unpublish":
        fields.update(is_unpublished=True, is_active=False, status=Listing.Status.DRAFT)
    elif action == "reactivate":
        fields.update(
            is_active=True, is_invalidated=False, is_unpublished=False,
            status=Listing.Status.ACTIVE, is_admin_cancelled=False,
        )
    else:
        return JsonResponse({"success": False, "error": "Неизвестное действие."}, status=400)
    # update() bypasses Listing.save()/full_clean so an admin can force a status
    # transition without tripping publish-time field validation.
    Listing.objects.filter(id=listing_id).update(**fields)
    return JsonResponse({"success": True, "listing": _listing_payload(Listing.objects.get(id=listing_id))})


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #
@superuser_required
@require_GET
def studio_reviews(request: HttpRequest) -> JsonResponse:
    qs = Review.objects.select_related("user").order_by("-created_at")
    return JsonResponse({"success": True, "reviews": [_review_payload(r) for r in qs[:200]]})


@superuser_required
@require_POST
def studio_review_action(request: HttpRequest, review_id: int) -> JsonResponse:
    review = Review.objects.filter(id=review_id).first()
    if not review:
        return JsonResponse({"success": False, "error": "Отзыв не найден."}, status=404)
    data = _json_body(request)
    action = str(data.get("action") or "").strip()
    reason = str(data.get("reason") or "").strip()
    if action == "hide":
        review.is_hidden = True
        review.hidden_reason = reason
        review.hidden_at = timezone.now()
        review.hidden_by = None
        review.save(update_fields=["is_hidden", "hidden_reason", "hidden_at", "hidden_by", "updated_at"])
    elif action == "restore":
        review.is_hidden = False
        review.hidden_reason = ""
        review.hidden_at = None
        review.hidden_by = None
        review.save(update_fields=["is_hidden", "hidden_reason", "hidden_at", "hidden_by", "updated_at"])
    elif action == "delete":
        review.delete()
        return JsonResponse({"success": True, "deleted": True})
    else:
        return JsonResponse({"success": False, "error": "Неизвестное действие."}, status=400)
    return JsonResponse({"success": True, "review": _review_payload(review)})
