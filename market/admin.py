"""Registers the market models in Django admin, replacing the Java admin screens."""
from django.contrib import admin

from .models import Bid, Listing, Message


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "item",
        "seller",
        "type",
        "price",
        "current_price",
        "is_active",
        "created_at",
    )
    list_filter = ("type", "is_active")
    search_fields = ("title", "description", "item__title", "seller__username")


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "bidder", "amount", "created_at")
    search_fields = ("listing__title", "bidder__username")
    list_select_related = ("listing", "bidder")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "sender", "recipient", "created_at")
    search_fields = ("text", "sender__username", "recipient__username")
    list_select_related = ("listing", "sender", "recipient")
