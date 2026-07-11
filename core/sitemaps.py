from __future__ import annotations

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from market.models import Listing


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return [
            "core:landing",
            "core:collector-service",
            "core:news",
            "core:reviews",
            "core:terms",
            "market_shop",
            "market_free",
            "market_wanted",
            "market_swap",
            "market_auction",
        ]

    def location(self, item):
        return reverse(item)


class ActiveListingSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.6

    def items(self):
        return Listing.objects.filter(is_active=True).order_by("-created_at")

    def lastmod(self, obj: Listing):
        return obj.created_at

    def location(self, obj: Listing):
        return reverse("market_listing_detail", args=[obj.pk])
