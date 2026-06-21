from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.services.subscriptions import ensure_free_subscription


@receiver(post_save, sender=get_user_model())
def ensure_user_free_subscription(sender, instance, created, **kwargs):
    if created:
        ensure_free_subscription(instance)
