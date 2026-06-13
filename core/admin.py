"""Admin registrations for core models."""
from django.contrib import admin

from .models import Friendship, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('login', 'name', 'last_name', 'city', 'mail', 'delete', 'update_date')
    search_fields = ('login', 'name', 'last_name', 'city', 'mail')
    list_filter = ('delete', 'city')


@admin.register(Friendship)
class FriendshipAdmin(admin.ModelAdmin):
    list_display = ('user_low', 'user_high', 'requester', 'status', 'created_at', 'updated_at', 'resolved_at')
    list_filter = ('status', 'created_at', 'updated_at', 'resolved_at')
    search_fields = ('user_low__username', 'user_high__username', 'requester__username')
    autocomplete_fields = ('user_low', 'user_high', 'requester')
    readonly_fields = ('created_at', 'updated_at')
