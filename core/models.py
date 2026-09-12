import uuid
from django.db import models

class DesktopPurchase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    payment_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    checkout_url = models.URLField(max_length=2048, blank=True)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)


class SupportTicket(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'Новое'
        WORK = 'work', 'В работе'
        ANSWERED = 'answered', 'Отвечено'
    email = models.EmailField()
    name = models.CharField(max_length=120)
    question = models.TextField(max_length=10000)
    source = models.CharField(max_length=16, default='website', editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    sender_hash = models.CharField(max_length=64, db_index=True, editable=False)
    submission_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ['-created_at', '-pk']


class SupportReply(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='replies')
    text = models.TextField(max_length=20000)
    sent_at = models.DateTimeField()
    request_id = models.UUIDField(unique=True, default=uuid.uuid4)
