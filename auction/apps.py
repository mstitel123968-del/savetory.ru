"""Configures the Auction app: lots derived from archive cards and their bids."""
from django.apps import AppConfig


class AuctionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'auction'
    verbose_name = 'Аукцион'
