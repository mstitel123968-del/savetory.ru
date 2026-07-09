"""Server-only access helpers for the hidden site editor."""
from __future__ import annotations

import hmac
import os

from django.conf import settings

ADMIN_SESSION_KEY = "studio_admin_authenticated"
ADMIN_LOGIN_SESSION_KEY = "studio_admin_login"


def configured_admin_login() -> str:
    return (os.environ.get("SUPERUSER_LOGIN") or "SuperUser").strip()


def configured_admin_password() -> str:
    password = os.environ.get("SUPERUSER_PASSWORD")
    if password:
        return password
    if settings.DEBUG:
        return "TS11181992SKlad"
    return ""


def is_reserved_admin_username(username: str) -> bool:
    login = configured_admin_login()
    return bool(login and str(username or "").strip().lower() == login.lower())


def check_admin_credentials(username: str, password: str) -> bool:
    login = configured_admin_login()
    configured_password = configured_admin_password()
    if not login or not configured_password:
        return False
    return (
        hmac.compare_digest(str(username or "").strip(), login)
        and hmac.compare_digest(str(password or ""), configured_password)
    )


def is_admin_session(request) -> bool:
    return bool(request.session.get(ADMIN_SESSION_KEY))


def start_admin_session(request) -> None:
    request.session[ADMIN_SESSION_KEY] = True
    request.session[ADMIN_LOGIN_SESSION_KEY] = configured_admin_login()
    request.session.modified = True


def end_admin_session(request) -> None:
    request.session.pop(ADMIN_SESSION_KEY, None)
    request.session.pop(ADMIN_LOGIN_SESSION_KEY, None)
    request.session.modified = True
