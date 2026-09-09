import uuid
from django.db import models

class DesktopPurchase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    payment_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    checkout_url = models.URLField(max_length=2048, blank=True)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
