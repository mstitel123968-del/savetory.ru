"""Admin registrations for core models."""
from django.contrib import admin

from .models import (
    DirectMessage,
    DirectMessageReaction,
    Friendship,
    Profile,
    SubscriptionHistory,
    SubscriptionPayment,
    SubscriptionPlan,
    UserProfile,
    UserSubscription,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('login', 'name', 'last_name', 'city', 'mail', 'delete', 'update_date')
    search_fields = ('login', 'name', 'last_name', 'city', 'mail')
    list_filter = ('delete', 'city')


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'display_name', 'privacy_level', 'is_hidden', 'terms_version_accepted', 'updated_at')
    list_filter = ('privacy_level', 'is_hidden', 'updated_at')
    search_fields = ('user__username', 'user__email', 'display_name')
    autocomplete_fields = ('user',)
    readonly_fields = ('updated_at',)


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


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'code',
        'archive_limit',
        'active_auction_limit',
        'is_paid',
        'is_active',
        'sort_order',
    )
    list_filter = ('is_paid', 'is_active')
    search_fields = ('name', 'code')


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'tariff', 'status', 'billing_period', 'starts_at', 'expires_at', 'last_successful_payment', 'auto_renew')
    list_filter = (
        'status',
        'billing_period',
        'auto_renew',
        'tariff',
        'user',
        ('starts_at', admin.DateFieldListFilter),
        ('expires_at', admin.DateFieldListFilter),
        ('created_at', admin.DateFieldListFilter),
    )
    search_fields = ('user__username', 'user__email', 'provider_payment_id')
    autocomplete_fields = ('user', 'tariff')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ('internal_uuid', 'user', 'tariff', 'period', 'amount', 'currency', 'status', 'paid_at', 'subscription_activated')
    list_filter = (
        'status',
        'period',
        'currency',
        'subscription_activated',
        'tariff',
        'user',
        ('created_at', admin.DateFieldListFilter),
        ('paid_at', admin.DateFieldListFilter),
        ('updated_at', admin.DateFieldListFilter),
    )
    search_fields = ('internal_uuid', 'user__username', 'user__email', 'yookassa_payment_id', 'idempotence_key')
    autocomplete_fields = ('user', 'tariff')
    date_hierarchy = 'created_at'
    readonly_fields = (
        'internal_uuid',
        'user',
        'tariff',
        'period',
        'amount',
        'currency',
        'status',
        'yookassa_payment_id',
        'idempotence_key',
        'confirmation_url',
        'metadata',
        'error_message',
        'paid_at',
        'subscription_activated',
        'created_at',
        'updated_at',
    )

    def has_add_permission(self, request):
        return False


@admin.register(SubscriptionHistory)
class SubscriptionHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'from_plan', 'to_plan', 'from_status', 'to_status', 'reason', 'changed_at')
    list_filter = ('reason', 'from_status', 'to_status', 'to_plan')
    search_fields = ('user__username', 'reason')
    autocomplete_fields = ('user', 'subscription', 'from_plan', 'to_plan')
    readonly_fields = ('changed_at',)
