"""Custom middleware for compliance checks."""
from __future__ import annotations

import logging
from datetime import datetime

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import resolve
from django.utils import timezone

from core import messages
from core.models import Profile

logger = logging.getLogger("core.moderation")

SAFE_METHODS: tuple[str, ...] = ("GET", "HEAD", "OPTIONS", "TRACE")
LAST_SEEN_SESSION_KEY = "profile_last_seen_update_at"
LAST_SEEN_UPDATE_INTERVAL_SECONDS = 60


class LastSeenMiddleware:
    """Update authenticated users' activity timestamp at most once per minute."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.user.is_authenticated:
            self._update_last_seen(request)
        return self.get_response(request)

    def _update_last_seen(self, request: HttpRequest) -> None:
        now = timezone.now()
        last_update = request.session.get(LAST_SEEN_SESSION_KEY)
        if last_update:
            try:
                previous = datetime.fromisoformat(last_update)
                if previous.tzinfo is None:
                    previous = timezone.make_aware(previous)
                if (now - previous).total_seconds() < LAST_SEEN_UPDATE_INTERVAL_SECONDS:
                    return
            except (TypeError, ValueError):
                pass

        Profile.objects.update_or_create(
            user=request.user,
            defaults={'last_seen_at': now},
        )
        request.session[LAST_SEEN_SESSION_KEY] = now.isoformat()


class BlockedUserMiddleware:
    """Prevent administratively blocked users from using the site.

    A blocked user keeps read (GET) access so they can see the block notice,
    but every data-modifying request is refused with the block reason. The
    reason is also exposed on ``request.blocked_notice`` for templates/banners.
    Superusers are never affected.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Let a blocked user still log out; everything else is refused.
        self.exempt_names: set[str] = {"core:logout"}

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.blocked_notice = ""
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not user.is_superuser:
            profile = getattr(user, "profile", None)
            if profile is not None and profile.is_blocked:
                request.blocked_notice = messages.blocked_message(profile)
                if request.method not in SAFE_METHODS and not self._is_exempt(request):
                    return self._block_response(request, profile)
        return self.get_response(request)

    def _is_exempt(self, request: HttpRequest) -> bool:
        try:
            match = resolve(request.path_info)
        except Exception:  # pragma: no cover
            return False
        full_name = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
        return full_name in self.exempt_names if full_name else False

    def _block_response(self, request: HttpRequest, profile) -> HttpResponse:
        message = messages.blocked_message(profile)
        logger.warning("Blocked %s %s from blocked user %s", request.method, request.path, request.user.pk)
        wants_json = (
            request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "json" in request.headers.get("accept", "")
            or request.path.startswith("/api/")
        )
        if wants_json:
            return JsonResponse({"success": False, "blocked": True, "errors": {"__all__": message}}, status=403)
        return HttpResponse(message, status=403)


class TermsAcceptanceMiddleware:
    """Require users to accept the latest terms before modifying data."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_names: set[str] = {
            "core:accept_terms",
            "core:terms",
            "core:logout",
            "core:login",
            "core:register",
        }

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.requires_terms_acceptance = False
        # Superusers (the site administrator/editor) are never gated by the
        # terms flow — they must be able to moderate content immediately.
        if request.user.is_authenticated and not request.user.is_superuser:
            profile, _ = Profile.objects.get_or_create(user=request.user)
            current = profile.terms_version_accepted or ""
            required = settings.TERMS_VERSION
            if current != required:
                request.requires_terms_acceptance = True
                if not self._is_exempt(request):
                    if request.method not in SAFE_METHODS:
                        return self._block_response(request)
        return self.get_response(request)

    def _is_exempt(self, request: HttpRequest) -> bool:
        try:
            match = resolve(request.path_info)
        except Exception:  # pragma: no cover - resolution errors should not block
            return False
        full_name = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
        return full_name in self.exempt_names if full_name else False

    def _block_response(self, request: HttpRequest) -> HttpResponse:
        logger.warning(
            "Blocked %s %s due to pending terms acceptance", request.method, request.path
        )
        wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest" or "json" in request.headers.get("accept", "") or request.path.startswith("/api/")
        if wants_json:
            return JsonResponse({"success": False, "errors": {"__all__": messages.TERMS_REQUIRED_ERROR}}, status=403)
        return HttpResponse(messages.TERMS_REQUIRED_ERROR, status=403)
