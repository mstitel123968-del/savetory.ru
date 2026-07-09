"""Clean up a legacy Django user that used the reserved editor login."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q

from core.admin_access import configured_admin_login
from core.models import DirectMessage, Friendship, Profile


class Command(BaseCommand):
    help = "Disable and hide a legacy Django user with the reserved editor login."

    def handle(self, *args, **options):
        login = configured_admin_login()
        if not login:
            self.stdout.write("SUPERUSER_LOGIN is empty; nothing to clean.")
            return

        User = get_user_model()
        user = User.objects.filter(username__iexact=login).first()
        if user is None:
            self.stdout.write(f"No legacy user '{login}' found.")
            return

        Friendship.objects.filter(
            Q(user_low=user) | Q(user_high=user) | Q(requester=user)
        ).delete()
        DirectMessage.objects.filter(Q(sender=user) | Q(recipient=user)).delete()

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_hidden = True
        profile.is_blocked = True
        profile.block_reason = "Reserved administrative editor login; not a public user."
        profile.save(update_fields=["is_hidden", "is_blocked", "block_reason", "updated_at"])

        user.is_staff = False
        user.is_superuser = False
        user.is_active = False
        user.set_unusable_password()
        user.save(update_fields=["is_staff", "is_superuser", "is_active", "password"])

        self.stdout.write(self.style.SUCCESS(f"Legacy user '{login}' disabled and hidden."))
