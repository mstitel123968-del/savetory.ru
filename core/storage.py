"""Staticfiles storage helpers for safer production rendering."""

try:
    from whitenoise.storage import CompressedManifestStaticFilesStorage as BaseStaticFilesStorage
except ImportError:  # pragma: no cover - optional dependency
    from django.contrib.staticfiles.storage import ManifestStaticFilesStorage as BaseStaticFilesStorage


class SafeManifestStaticFilesStorage(BaseStaticFilesStorage):
    """Do not raise template-time errors when manifest is temporarily stale."""

    manifest_strict = False
