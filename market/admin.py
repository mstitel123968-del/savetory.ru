"""Registers the market models in Django admin, replacing the Java admin screens."""
from django.contrib import admin

from .models import AuctionBid, Bid, Listing, ListingImage, Message


class ListingImageInline(admin.TabularInline):
    model = ListingImage
    extra = 0
    fields = ("source_image", "image", "display_order", "is_cover", "created_at")
    readonly_fields = ("created_at",)
    raw_id_fields = ("source_image",)


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "item",
        "seller",
        "type",
        "status",
        "price",
        "current_price",
        "is_active",
        "created_at",
    )
    list_filter = ("type", "status", "is_active", "item_condition")
    search_fields = ("title", "description", "item__title", "seller__username")
    inlines = [ListingImageInline]


@admin.register(ListingImage)
class ListingImageAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "display_order", "is_cover", "source_image", "created_at")
    list_filter = ("is_cover",)
    search_fields = ("listing__title",)
    raw_id_fields = ("listing", "source_image")


@admin.register(AuctionBid)
class AuctionBidAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "bidder", "amount", "previous_price", "is_winning", "created_at")
    list_filter = ("is_winning",)
    search_fields = ("listing__title", "bidder__username")
    list_select_related = ("listing", "bidder")
    readonly_fields = ("listing", "bidder", "amount", "previous_price", "is_winning", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
