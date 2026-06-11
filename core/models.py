"""Replaces the original Java entity classes with Django ORM models."""
import json

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
    link = models.CharField(max_length=255, blank=True, default='')
    terms_version_accepted = models.CharField(max_length=20, blank=True, default='')
    terms_accepted_at = models.DateTimeField(blank=True, null=True)
    terms_accepted_ip = models.GenericIPAddressField(blank=True, null=True)

    def __str__(self) -> str:  # pragma: no cover
        return self.display_name or self.user.get_username()

    def clean(self) -> None:
        if self.avatar:
            moderation.validate_uploaded_file(self.avatar)

    def mark_terms_accepted(self, *, ip: str | None = None) -> None:
        self.terms_version_accepted = settings.TERMS_VERSION
        self.terms_accepted_at = timezone.now()
        if ip:
            self.terms_accepted_ip = ip
        self.save(update_fields=['terms_version_accepted', 'terms_accepted_at', 'terms_accepted_ip'])

    def has_accepted_terms(self) -> bool:
        return (self.terms_version_accepted or '') == settings.TERMS_VERSION


class Rubric(models.Model):
    """Represents archive categories, replacing the Java Rubric entity."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='rubrics')
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    is_text_mode = models.BooleanField(default=False)
    field_schema = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

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

    rubric = models.ForeignKey(Rubric, on_delete=models.CASCADE, related_name='files')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='archive_files',
    )
    title = models.CharField(max_length=255)
    normalized_title = models.CharField(max_length=255, blank=True, default='')
    content_hash = models.CharField(max_length=64, blank=True, default='')
    data = models.JSONField(default=dict)
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
