"""Admin registration for auction lots (bids live on market.Bid)."""
from django.contrib import admin

from .models import AuctionLot


@admin.register(AuctionLot)
class AuctionLotAdmin(admin.ModelAdmin):
    list_display = ('id', 'listing', 'status', 'current_price', 'start_at', 'end_at', 'winner', 'created_at')
    list_filter = ('status', 'auto_extend')
    search_fields = ('id', 'listing__id', 'listing__seller__username')
    raw_id_fields = ('listing', 'winner')
    readonly_fields = ('snapshot', 'snapshot_images', 'published_at', 'created_at', 'updated_at')
