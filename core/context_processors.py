"""Custom context processors for the core app."""
from __future__ import annotations

from django.conf import settings
from django.urls import reverse

from core.services import subscriptions


def terms(request):
    """Expose terms flags and shared authenticated-shell data to templates."""
    requires_terms = getattr(request, "requires_terms_acceptance", False)
    context = {
        "terms_required": requires_terms,
        "terms_version": settings.TERMS_VERSION,
        "terms_accept_url": reverse("core:accept_terms"),
        "terms_page_url": reverse("core:terms"),
    }

    if request.user.is_authenticated:
        snapshot = subscriptions.archive_limit_snapshot(request.user)
        archive_limit = snapshot.archive_limit
        archive_used = subscriptions.archive_display_usage(request.user)
        usage_percent = 0
        if archive_limit:
            usage_percent = min(100, round((archive_used / archive_limit) * 100))
        context.update(
            {
                "app_subscription": snapshot.subscription,
                "app_subscription_plan": snapshot.tariff,
                "app_archive_used": archive_used,
                "app_archive_limit": archive_limit,
                "app_archive_limit_label": subscriptions.archive_limit_label(archive_limit),
                "app_archive_usage_percent": usage_percent,
            }
        )

    return context
