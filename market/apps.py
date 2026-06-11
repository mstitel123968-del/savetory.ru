"""Configures the Market app that mirrors the Java market package."""
from django.apps import AppConfig


class MarketConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'market'
    verbose_name = 'Маркет'
