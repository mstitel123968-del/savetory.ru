"""Utilities for server-side content moderation and duplicate detection."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.core.exceptions import ValidationError

from core import messages

logger = logging.getLogger("core.moderation")

_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+", re.UNICODE)


def _ensure_iterable(value: Iterable[str] | str) -> Iterable[str]:
    if isinstance(value, str):
        return (value,)
    return value


def normalise_text(value: str) -> str:
    """Return a trimmed, lower-cased text with collapsed whitespace."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    lowered = normalized.lower()
    collapsed = _SPACE_RE.sub(" ", lowered)
    return collapsed.strip()


def alnum_fingerprint(value: str) -> str:
    """Strip everything but letters and digits to catch masked terms."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    lowered = normalized.lower()
    return _WORD_RE.sub("", lowered)


def find_banned_word(value: str) -> str | None:
    """Return the first banned word found in *value*, if any."""
    if not value:
        return None
    normalised_value = normalise_text(value)
    alnum_value = alnum_fingerprint(value)
    for raw_word in getattr(settings, "BANNED_WORDS", ()):  # type: ignore[attr-defined]
        word = normalise_text(raw_word)
        if not word:
            continue
        compact = alnum_fingerprint(raw_word)
        if word and word in normalised_value:
            return raw_word
        if compact and compact in alnum_value:
            return raw_word
    return None


def ensure_text_allowed(value: str, *, field: str | None = None) -> None:
    """Raise :class:`ValidationError` when value contains a banned word."""
    banned = find_banned_word(value)
    if banned:
        logger.warning("Blocked text containing banned word %s", banned)
        message = messages.BANNED_WORD_ERROR.format(word=banned)
        if field:
            raise ValidationError(message)
        raise ValidationError({"__all__": message})


def ensure_payload_allowed(payload: Iterable[str]) -> None:
    """Validate a sequence of text fragments."""
    for chunk in _ensure_iterable(payload):
        ensure_text_allowed(chunk)


def validate_uploaded_file(upload) -> None:
    """Validate uploaded files against project restrictions."""
    if upload is None:
        return
    max_size_mb = getattr(settings, "MAX_FILE_SIZE_MB", 10)
    size_limit = max_size_mb * 1024 * 1024
    file_size = getattr(upload, "size", None)
    if file_size is not None and file_size > size_limit:
        logger.warning("Blocked upload larger than limit: %s bytes", file_size)
        raise ValidationError(messages.FILE_SIZE_ERROR.format(limit=max_size_mb))

    extension = Path(getattr(upload, "name", "")).suffix.lower()
    banned_extensions = {ext.lower() for ext in getattr(settings, "BANNED_EXTENSIONS", [])}
    if extension and extension in banned_extensions:
        logger.warning("Blocked upload with forbidden extension: %s", extension)
        raise ValidationError(messages.FILE_EXTENSION_ERROR.format(ext=extension))

    content_type = getattr(upload, "content_type", "")
    banned_mimes = {mime.lower() for mime in getattr(settings, "BANNED_MIME_TYPES", [])}
    if content_type and content_type.lower() in banned_mimes:
        logger.warning("Blocked upload with forbidden MIME type: %s", content_type)
        raise ValidationError(messages.FILE_MIME_ERROR.format(mime=content_type))


def serialise_content_for_hash(title: str, data) -> str:
    """Create a canonical string representation used for hashing."""
    title_part = normalise_text(title)
    if isinstance(data, (dict, list)):
        try:
            data_part = json.dumps(data, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            data_part = normalise_text(str(data))
    else:
        data_part = normalise_text(str(data))
    return f"{title_part}\n{data_part}".strip()


def compute_content_hash(title: str, data) -> str:
    """Return SHA-256 hash for archive content."""
    payload = serialise_content_for_hash(title, data)
    if not payload:
        return ""
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return digest
