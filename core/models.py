"""Replaces the original Java entity classes with Django ORM models."""
import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.utils import moderation


class UserProfile(models.Model):
    """Stores profile data persisted in the new PostgreSQL database."""

    login = models.CharField(max_length=255, unique=True)
    passwor = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    city = models.CharField(max_length=255)
    mail = models.EmailField(max_length=255)
    link = models.CharField(max_length=255)
    telephone = models.CharField(max_length=255)
    interests = models.TextField()
    create_date = models.DateTimeField(auto_now_add=True)
    update_date = models.DateTimeField(auto_now=True)
    delete = models.IntegerField(default=0)

    class Meta:
        ordering = ['login']

    def __str__(self) -> str:  # pragma: no cover
        return self.login


class Profile(models.Model):
    """Stores user profile metadata formerly held in a Java Profile entity."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name = models.CharField(max_length=150, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    avatar_meta = models.JSONField(default=dict, blank=True)
    privacy_level = models.CharField(max_length=50, default='public')
    last_seen_at = models.DateTimeField(blank=True, null=True, db_index=True)
    bio = models.TextField(blank=True, default='')
    background_image = models.CharField(max_length=255, blank=True, default='')
    link = models.CharField(max_length=255, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    terms_version_accepted = models.CharField(max_length=20, blank=True, default='')
    terms_accepted_at = models.DateTimeField(blank=True, null=True)
    terms_accepted_ip = models.GenericIPAddressField(blank=True, null=True)

    def __str__(self) -> str:  # pragma: no cover
        return self.display_name or self.user.get_username()

    def clean(self) -> None:
        if self.avatar:
            moderation.validate_uploaded_file(self.avatar)
        if self.bio:
            moderation.ensure_text_allowed(self.bio, field='bio')
        if self.link and not (self.link.startswith('http://') or self.link.startswith('https://')):
            raise ValidationError({'link': 'Profile link must start with http:// or https://.'})

    def mark_terms_accepted(self, *, ip: str | None = None) -> None:
        self.terms_version_accepted = settings.TERMS_VERSION
        self.terms_accepted_at = timezone.now()
        if ip:
            self.terms_accepted_ip = ip
        self.save(update_fields=['terms_version_accepted', 'terms_accepted_at', 'terms_accepted_ip'])

    def has_accepted_terms(self) -> bool:
        return (self.terms_version_accepted or '') == settings.TERMS_VERSION


class Friendship(models.Model):
    """Stores a normalized friendship or friendship request between two users."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'

    user_low = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='friendships_as_low',
    )
    user_high = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='friendships_as_high',
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_friendship_requests',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['user_low', 'user_high'], name='uniq_friendship_pair'),
            models.CheckConstraint(check=models.Q(user_low_id__lt=models.F('user_high_id')), name='friendship_ordered_pair'),
            models.CheckConstraint(
                check=models.Q(requester_id=models.F('user_low_id')) | models.Q(requester_id=models.F('user_high_id')),
                name='friendship_requester_is_participant',
            ),
        ]
        indexes = [
            models.Index(fields=['user_low', 'status'], name='friend_low_status_idx'),
            models.Index(fields=['user_high', 'status'], name='friend_high_status_idx'),
            models.Index(fields=['requester', 'status'], name='friend_requester_status_idx'),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Friendship<{self.user_low_id}:{self.user_high_id}:{self.status}>"

    @staticmethod
    def normalize_pair(user_a, user_b):
        user_a_id = getattr(user_a, 'pk', user_a)
        user_b_id = getattr(user_b, 'pk', user_b)
        if not user_a_id or not user_b_id:
            raise ValidationError('Both users must be saved before creating a friendship.')
        if user_a_id == user_b_id:
            raise ValidationError('A user cannot create a friendship with themselves.')
        return (user_a, user_b) if user_a_id < user_b_id else (user_b, user_a)

    def clean(self) -> None:
        super().clean()
        if self.user_low_id and self.user_high_id and self.user_low_id == self.user_high_id:
            raise ValidationError('A user cannot create a friendship with themselves.')
        if self.user_low_id and self.user_high_id and self.user_low_id > self.user_high_id:
            self.user_low_id, self.user_high_id = self.user_high_id, self.user_low_id
        if self.requester_id and self.user_low_id and self.user_high_id:
            if self.requester_id not in {self.user_low_id, self.user_high_id}:
                raise ValidationError({'requester': 'Requester must be one of the friendship participants.'})

    def save(self, *args, **kwargs) -> None:
        if self.user_low_id and self.user_high_id and self.user_low_id > self.user_high_id:
            self.user_low_id, self.user_high_id = self.user_high_id, self.user_low_id
        super().save(*args, **kwargs)


class DirectMessage(models.Model):
    """Stores a private message between two registered users."""

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_direct_messages',
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_direct_messages',
    )
    # Text may be empty when the message carries only an attachment.
    text = models.TextField(blank=True, default='')
    sent_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(blank=True, null=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)

    # Optional file/image attachment stored on the project's default storage
    # (Yandex S3 when enabled, local filesystem otherwise).
    attachment = models.FileField(upload_to='message_attachments/%Y/%m/', blank=True, null=True)
    attachment_name = models.CharField(max_length=255, blank=True, default='')
    attachment_size = models.PositiveBigIntegerField(null=True, blank=True)
    attachment_content_type = models.CharField(max_length=120, blank=True, default='')
    attachment_kind = models.CharField(max_length=10, blank=True, default='')  # 'image' | 'file'

    class Meta:
        ordering = ['sent_at', 'id']
        indexes = [
            models.Index(fields=['sender', 'recipient', 'sent_at'], name='dm_sender_recipient_idx'),
            models.Index(fields=['recipient', 'sender', 'sent_at'], name='dm_recipient_sender_idx'),
            models.Index(fields=['recipient', 'is_read'], name='dm_recipient_read_idx'),
        ]
        constraints = [
            models.CheckConstraint(check=~models.Q(sender_id=models.F('recipient_id')), name='dm_sender_not_recipient'),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"DirectMessage<{self.sender_id}->{self.recipient_id}:{self.sent_at:%Y-%m-%d %H:%M:%S}>"

    @property
    def has_attachment(self) -> bool:
        return bool(self.attachment)

    @property
    def is_image_attachment(self) -> bool:
        return self.attachment_kind == 'image'

    def clean(self) -> None:
        super().clean()
        if self.sender_id and self.recipient_id and self.sender_id == self.recipient_id:
            raise ValidationError('A user cannot send a message to themselves.')
        if self.text:
            moderation.ensure_text_allowed(self.text, field='text')


class DirectMessageReaction(models.Model):
    """Stores one reaction per user for a private message."""

    class Reaction(models.TextChoices):
        THUMBS_UP = '👍', 'Thumbs up'
        HEART = '❤️', 'Heart'
        LAUGH = '😂', 'Laugh'
        WOW = '😮', 'Wow'
        SAD = '😢', 'Sad'

    message = models.ForeignKey(
        DirectMessage,
        on_delete=models.CASCADE,
        related_name='reactions',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='direct_message_reactions',
    )
    reaction = models.CharField(max_length=8, choices=Reaction.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['message_id', 'reaction', 'id']
        constraints = [
            models.UniqueConstraint(fields=['message', 'user'], name='uniq_dm_reaction_per_user'),
        ]
        indexes = [
            models.Index(fields=['message', 'reaction'], name='dm_reaction_message_idx'),
            models.Index(fields=['user', 'updated_at'], name='dm_reaction_user_idx'),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"DirectMessageReaction<{self.message_id}:{self.user_id}:{self.reaction}>"

    def clean(self) -> None:
        super().clean()
        if self.message_id and self.user_id:
            participant_ids = {self.message.sender_id, self.message.recipient_id}
            if self.user_id not in participant_ids:
                raise ValidationError('Only conversation participants can react to a message.')


class Rubric(models.Model):
    """Represents archive categories, replacing the Java Rubric entity."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='rubrics')
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    # System rubrics (e.g. the «Аукцион» rubric) are managed by the platform:
    # they cannot be renamed, deleted, have their fields changed, or receive
    # cards moved in manually. Regular user rubrics keep is_system=False.
    is_system = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)
    public_slug = models.SlugField(max_length=255, blank=True, default='', allow_unicode=True, db_index=True)
    is_text_mode = models.BooleanField(default=False)
    field_schema = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('profile', 'slug')
        ordering = ['created_at']

    def __str__(self) -> str:  # pragma: no cover
        return self.name

    def clean(self) -> None:
        if self.name:
            moderation.ensure_text_allowed(self.name, field='name')


class ArchiveFile(models.Model):
    """Stores archive items, replacing the Java ArchiveFile entity."""

    class Status(models.TextChoices):
        KEEP = 'keep', 'Храню'
        SELL = 'sell', 'Готов продать'
        EXCHANGE = 'exchange', 'Готов обменять'
        SEARCH = 'search', 'Ищу такой же'
        SOLD = 'sold', 'Продано'

    rubric = models.ForeignKey(Rubric, on_delete=models.CASCADE, related_name='files')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='archive_files',
    )
    title = models.CharField(max_length=255)
    normalized_title = models.CharField(max_length=255, blank=True, default='')
    content_hash = models.CharField(max_length=64, blank=True, default='')
    data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.KEEP)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'normalized_title'],
                name='uniq_archive_owner_title',
            ),
            models.UniqueConstraint(
                fields=['owner', 'content_hash'],
                name='uniq_archive_owner_hash',
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return self.title

    def update_signatures(self) -> None:
        if self.rubric and self.rubric_id and self.rubric.profile_id:
            self.owner = self.rubric.profile.user
        self.normalized_title = moderation.normalise_text(self.title)
        try:
            data_value = self.data
        except AttributeError:  # pragma: no cover - guard for weird JSONField usage
            data_value = {}
        self.content_hash = moderation.compute_content_hash(self.title, data_value)

    def clean(self) -> None:
        errors: dict[str, list[str]] = {}
        try:
            moderation.ensure_text_allowed(self.title, field='title')
        except ValidationError as exc:
            errors.setdefault('title', []).extend(exc.messages)

        try:
            payload = json.dumps(self.data, ensure_ascii=False) if isinstance(self.data, (dict, list)) else str(self.data)
            moderation.ensure_text_allowed(payload, field='data')
        except (TypeError, ValueError):
            pass
        except ValidationError as exc:
            errors.setdefault('data', []).extend(exc.messages)

        if errors:
            raise ValidationError(errors)

    def full_clean(self, *args, **kwargs) -> None:
        self.update_signatures()
        super().full_clean(*args, **kwargs)

    def save(self, *args, **kwargs) -> None:
        self.update_signatures()
        super().save(*args, **kwargs)


class ArchiveFileImage(models.Model):
    """Stores multiple images for an archive file, replacing the Java ArchiveFileImage entity."""

    archive_file = models.ForeignKey(ArchiveFile, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='archive/')
    display_order = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.archive_file}: {self.display_order}"

    def clean(self) -> None:
        if self.image:
            moderation.validate_uploaded_file(self.image)


class ArchiveState(models.Model):
    """Server-side source of truth for archive UI state."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='archive_state')
    data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"ArchiveState<{self.user_id}>"


class SubscriptionPlan(models.Model):
    """Account tariff with limits managed from Django Admin."""

    class Code(models.TextChoices):
        FREE = 'free', 'Free'
        PLUS = 'plus', 'Plus'
        PRO = 'pro', 'Pro'

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True, default='')
    archive_limit = models.PositiveIntegerField(null=True, blank=True)
    active_auction_limit = models.PositiveIntegerField()
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    yearly_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class UserSubscription(models.Model):
    """Current or historical subscription interval for a user account."""

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        EXPIRED = 'expired', 'Expired'
        CANCELED = 'canceled', 'Canceled'

    class BillingPeriod(models.TextChoices):
        FREE = 'free', 'Free'
        MONTH = 'month', 'Month'
        YEAR = 'year', 'Year'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscriptions')
    tariff = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='subscriptions')
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_successful_payment = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    billing_period = models.CharField(max_length=16, choices=BillingPeriod.choices, default=BillingPeriod.FREE)
    auto_renew = models.BooleanField(default=False)
    provider = models.CharField(max_length=32, blank=True, default='')
    provider_payment_id = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-starts_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(status='active'),
                name='uniq_active_subscription_per_user',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'status'], name='usersub_user_status_idx'),
            models.Index(fields=['status', 'expires_at'], name='usersub_status_exp_idx'),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.user_id}: {self.tariff.code} ({self.status})"

    @property
    def plan(self):  # Backwards-compatible alias for older service/view code.
        return self.tariff

    @plan.setter
    def plan(self, value) -> None:
        self.tariff = value

    @property
    def ends_at(self):  # Backwards-compatible alias for templates/tests.
        return self.expires_at

    @ends_at.setter
    def ends_at(self, value) -> None:
        self.expires_at = value


class SubscriptionPayment(models.Model):
    """Payment attempt prepared for a future YooKassa integration."""

    class Period(models.TextChoices):
        MONTH = 'month', 'Month'
        YEAR = 'year', 'Year'

    class Status(models.TextChoices):
        CREATED = 'created', 'Created'
        PENDING = 'pending', 'Pending'
        SUCCEEDED = 'succeeded', 'Succeeded'
        CANCELED = 'canceled', 'Canceled'
        FAILED = 'failed', 'Failed'

    internal_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscription_payments')
    tariff = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='payments')
    period = models.CharField(max_length=16, choices=Period.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='RUB')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATED, db_index=True)
    yookassa_payment_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    idempotence_key = models.CharField(max_length=128, unique=True)
    confirmation_url = models.URLField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default='')
    paid_at = models.DateTimeField(null=True, blank=True)
    subscription_activated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['user', 'status'], name='subpay_user_status_idx'),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"SubscriptionPayment<{self.internal_uuid}:{self.status}>"


class SubscriptionHistory(models.Model):
    """Audit trail for subscription status and plan changes."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscription_history')
    subscription = models.ForeignKey(UserSubscription, on_delete=models.SET_NULL, null=True, blank=True, related_name='history')
    from_plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    to_plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    from_status = models.CharField(max_length=16, blank=True, default='')
    to_status = models.CharField(max_length=16, blank=True, default='')
    billing_period = models.CharField(max_length=16, blank=True, default='')
    reason = models.CharField(max_length=120, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at', '-id']
        indexes = [
            models.Index(fields=['user', 'changed_at'], name='subhist_user_changed_idx'),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"SubscriptionHistory<{self.user_id}:{self.reason}>"


class Review(models.Model):
    """User review stored in DB instead of browser localStorage."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField(default=5)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:  # pragma: no cover
        return f"Review<{self.user_id}:{self.rating}>"
