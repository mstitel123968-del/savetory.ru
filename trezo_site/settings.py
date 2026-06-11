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

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or os.environ.get('SECRET_KEY', 'django-insecure-change-me')
DEBUG = os.environ.get('DJANGO_DEBUG', os.environ.get('DEBUG', '1')) == '1'
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

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.sitemaps',
    'django.contrib.staticfiles',
    'core',
    'market',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
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

STORAGES = {
    'staticfiles': {
        'BACKEND': 'core.storage.SafeManifestStaticFilesStorage',
    },
}

if USE_WHITENOISE:
    WHITENOISE_USE_FINDERS = True

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

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
