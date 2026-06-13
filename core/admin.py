"""Admin registrations for core models."""
from django.contrib import admin

from .models import DirectMessage, DirectMessageReaction, Friendship, UserProfile


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


@admin.register(DirectMessage)
class DirectMessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'recipient', 'sent_at', 'edited_at', 'is_deleted', 'is_read')
    list_filter = ('is_deleted', 'is_read', 'sent_at', 'edited_at', 'deleted_at')
    search_fields = ('sender__username', 'recipient__username', 'text')
    autocomplete_fields = ('sender', 'recipient')
    readonly_fields = ('sent_at', 'edited_at', 'deleted_at')


@admin.register(DirectMessageReaction)
class DirectMessageReactionAdmin(admin.ModelAdmin):
    list_display = ('message', 'user', 'reaction', 'created_at', 'updated_at')
    list_filter = ('reaction', 'created_at', 'updated_at')
    search_fields = ('message__text', 'user__username')
    autocomplete_fields = ('message', 'user')
    readonly_fields = ('created_at', 'updated_at')
