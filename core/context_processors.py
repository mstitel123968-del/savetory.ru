"""Custom context processors for the core app."""
from __future__ import annotations

from django.conf import settings
from django.urls import reverse


def terms(request):
    """Expose terms acceptance flags to templates."""
    requires_terms = getattr(request, "requires_terms_acceptance", False)
    return {
        "terms_required": requires_terms,
        "terms_version": settings.TERMS_VERSION,
        "terms_accept_url": reverse("core:accept_terms"),
        "terms_page_url": reverse("core:terms"),
    }
