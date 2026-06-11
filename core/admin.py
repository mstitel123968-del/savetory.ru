"""Admin registrations for core models."""
from django.contrib import admin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('login', 'name', 'last_name', 'city', 'mail', 'delete', 'update_date')
    search_fields = ('login', 'name', 'last_name', 'city', 'mail')
    list_filter = ('delete', 'city')
