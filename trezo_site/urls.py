"""Replaces the Java web.xml routing with Django URL configuration."""
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from core import views as core_views
from core.sitemaps import ActiveListingSitemap, StaticViewSitemap
from market import views as market_views

sitemaps = {
    'static': StaticViewSitemap,
    'listings': ActiveListingSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', core_views.robots_txt, name='robots-txt'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('', include(('core.urls', 'core'), namespace='core')),
    path('market/', core_views.market_closed, name='market-closed'),
    path('market/<path:path>', core_views.market_closed, name='market-closed-path'),
    path('market/', include('market.urls')),
    path('auction/', include('auction.urls')),
    path('messages/', market_views.market_messages, name='messages'),
]

if settings.DEBUG or getattr(settings, 'SERVE_MEDIA_FILES', False):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
