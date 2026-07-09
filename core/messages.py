"""User-facing and logging messages for moderation, duplicates, and terms checks."""

BANNED_WORD_ERROR = "Текст содержит запрещённое слово: «{word}»."
FILE_EXTENSION_ERROR = "Файлы с расширением «{ext}» недопустимы."
FILE_MIME_ERROR = "Файлы с типом «{mime}» недопустимы."
FILE_SIZE_ERROR = "Файл превышает допустимый размер {limit} МБ."
DUPLICATE_TITLE_ERROR = "Запись с таким названием уже существует (ID: {id})."
DUPLICATE_CONTENT_ERROR = "Запись с таким содержимым уже существует (ID: {id})."
TERMS_REQUIRED_ERROR = "Для продолжения примите пользовательское соглашение."
TERMS_DECLINED_ERROR = "Действие недоступно без принятия пользовательского соглашения."
TERMS_ACCEPTED_LOG = "Пользователь %s принял условия версии %s."
TERMS_ACCEPTED_TOAST = "Пользовательское соглашение принято."

BLOCKED_GENERIC = "Профиль заблокирован администратором."


def blocked_message(profile) -> str:
    """Build the block notice shown to a blocked user."""
    reason = (getattr(profile, 'block_reason', '') or '').strip()
    if reason:
        return f"Профиль заблокирован. Причина: {reason}"
    return BLOCKED_GENERIC
