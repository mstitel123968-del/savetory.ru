"""Replaces the former Java Spring configuration with Django project settings."""
from pathlib import Path
import os

try:  # WhiteNoise is optional; fall back to Django's static handler if missing.
    import whitenoise  # noqa: F401
except ImportError:
    USE_WHITENOISE = False
else:
    USE_WHITENOISE = True

BASE_DIR = Path(__file__).resolve().parent.parent

from django.core.exceptions import ImproperlyConfigured

_INSECURE_SECRET_KEY = 'django-insecure-change-me'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or os.environ.get('SECRET_KEY', _INSECURE_SECRET_KEY)
# Secure by default: DEBUG is only enabled when explicitly requested via the
# environment. Local development should set DJANGO_DEBUG=1 (or DEBUG=1).
DEBUG = os.environ.get('DJANGO_DEBUG', os.environ.get('DEBUG', '0')) == '1'

# Refuse to boot a production (DEBUG=0) instance that still relies on the
# placeholder secret key — this prevents accidental deploys with a known key.
if not DEBUG and SECRET_KEY in {_INSECURE_SECRET_KEY, '', 'changeme'}:
    raise ImproperlyConfigured(
        'A strong DJANGO_SECRET_KEY must be set when DEBUG is disabled.'
    )
_allowed_hosts = os.environ.get('DJANGO_ALLOWED_HOSTS')
if _allowed_hosts:
    ALLOWED_HOSTS: list[str] = _allowed_hosts.split()
else:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']


_csrf_origins = os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '')
if _csrf_origins.strip():
    CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in _csrf_origins.replace(',', ' ').split() if origin.strip()]
else:
    _default_origins: list[str] = []
    for host in ALLOWED_HOSTS:
        if host in {'localhost', '127.0.0.1', '[::1]'}:
            _default_origins.extend(['http://localhost', 'http://127.0.0.1'])
            continue
        _default_origins.extend([f'http://{host}', f'https://{host}'])
    CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(_default_origins))

if os.environ.get('DJANGO_SECURE_PROXY_SSL_HEADER', '0') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

USE_X_FORWARDED_HOST = os.environ.get('DJANGO_USE_X_FORWARDED_HOST', '0') == '1'
SESSION_COOKIE_SECURE = os.environ.get('DJANGO_SESSION_COOKIE_SECURE', '0') == '1'
CSRF_COOKIE_SECURE = os.environ.get('DJANGO_CSRF_COOKIE_SECURE', '0') == '1'

# Hardening headers. Sensible defaults that do not break HTTP-only local dev;
# HTTPS-only behaviour (redirect/HSTS) stays opt-in via the environment so it
# cannot lock out a deployment that is not fully on TLS yet.
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
# NB: CSRF cookie must stay readable by JS — the frontend reads the csrftoken
# cookie to send the X-CSRFToken header, so CSRF_COOKIE_HTTPONLY is left False.
X_FRAME_OPTIONS = os.environ.get('DJANGO_X_FRAME_OPTIONS', 'DENY')
SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SECURE_SSL_REDIRECT', '0') == '1'
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '0') or '0')
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', '0') == '1'
SECURE_HSTS_PRELOAD = os.environ.get('DJANGO_SECURE_HSTS_PRELOAD', '0') == '1'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.sitemaps',
    'django.contrib.staticfiles',
    'storages',
    'core',
    'market',
    'auction',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.LastSeenMiddleware',
    'core.middleware.TermsAcceptanceMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if USE_WHITENOISE:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'trezo_site.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'core' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.terms',
            ],
        },
    },
]

WSGI_APPLICATION = 'trezo_site.wsgi.application'
ASGI_APPLICATION = 'trezo_site.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': os.environ.get('POSTGRES_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.environ.get('POSTGRES_DB', 'user_bd'),
        'USER': os.environ.get('POSTGRES_USER', 'user_bd'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'user123968'),
        'HOST': os.environ.get('POSTGRES_HOST', 'db'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'core' / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# --- User media storage --------------------------------------------------------
# User-uploaded media defaults to the local filesystem. Yandex Object Storage
# (S3-compatible API) is an opt-in alternative, enabled only when
# YANDEX_STORAGE_ENABLED=1 and the AWS_* credentials below are provided via the
# environment. Static files are intentionally left untouched — they keep using
# WhiteNoise / the manifest storage backend and are never moved to S3.
YANDEX_STORAGE_ENABLED = os.environ.get('YANDEX_STORAGE_ENABLED', '0') == '1'

if YANDEX_STORAGE_ENABLED:
    _MEDIA_STORAGE = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'access_key': os.environ.get('AWS_ACCESS_KEY_ID'),
            'secret_key': os.environ.get('AWS_SECRET_ACCESS_KEY'),
            'bucket_name': os.environ.get('AWS_STORAGE_BUCKET_NAME'),
            'endpoint_url': os.environ.get('AWS_S3_ENDPOINT_URL'),
            'region_name': os.environ.get('AWS_S3_REGION_NAME'),
            'location': 'media',
            'default_acl': None,
            'querystring_auth': True,
            'querystring_expire': 3600,
            'file_overwrite': False,
            'signature_version': 's3v4',
            'addressing_style': 'path',
        },
    }
else:
    _MEDIA_STORAGE = {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    }

STORAGES = {
    'default': _MEDIA_STORAGE,
    'staticfiles': {
        'BACKEND': 'core.storage.SafeManifestStaticFilesStorage',
    },
}

if USE_WHITENOISE:
    WHITENOISE_USE_FINDERS = True

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
SERVE_MEDIA_FILES = DEBUG or os.environ.get('DJANGO_SERVE_MEDIA', '0') == '1'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/'
LOGIN_REDIRECT_URL = '/archive/'

# --- Moderation and compliance -------------------------------------------------
# Update these lists when policies change. Settings administrators can adjust
# banned vocabulary, file types and size limits in one place without touching
# business logic.
BANNED_WORDS = [
    'спам',
    'spam',
    'мошенничество',
    'fraud',
    'экстремизм',
    'extremism',
]
BANNED_MIME_TYPES = [
    'application/x-msdownload',
    'text/javascript',
]
BANNED_EXTENSIONS = ['.exe', '.js', '.bat', '.cmd']
MAX_FILE_SIZE_MB = int(os.environ.get('MAX_UPLOAD_MB', '10'))

# Bump this version whenever the public terms text changes. Users must re-accept
# the latest version before continuing to use interactive features.
TERMS_VERSION = os.environ.get('TERMS_VERSION', '2024-01')

# --- YooKassa payments --------------------------------------------------------
YOOKASSA_ENABLED = os.environ.get('YOOKASSA_ENABLED', '0') == '1'
YOOKASSA_SHOP_ID = os.environ.get('YOOKASSA_SHOP_ID', '')
YOOKASSA_SECRET_KEY = os.environ.get('YOOKASSA_SECRET_KEY', '')
SITE_URL = os.environ.get('SITE_URL', '')
YOOKASSA_RETURN_URL = os.environ.get('YOOKASSA_RETURN_URL', '')
YOOKASSA_SEND_RECEIPT = os.environ.get('YOOKASSA_SEND_RECEIPT', '0') == '1'
YOOKASSA_VAT_CODE = os.environ.get('YOOKASSA_VAT_CODE', '')
