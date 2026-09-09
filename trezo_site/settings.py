"""Download page and application licensing only."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
def flag(name, default=False):
    return os.environ.get(name, '1' if default else '0').lower() in ('1', 'true', 'yes')
DEBUG = flag('DJANGO_DEBUG', flag('DEBUG'))
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or os.environ.get('SECRET_KEY', '')
if not SECRET_KEY or SECRET_KEY in ('django-insecure-change-me', 'changeme'):
    if not DEBUG:
        raise ImproperlyConfigured('Set DJANGO_SECRET_KEY for production.')
    SECRET_KEY = 'local-download-site-development-only'
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost 127.0.0.1 [::1]').split()
INSTALLED_APPS = ['django.contrib.staticfiles', 'core']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.middleware.common.CommonMiddleware',
              'django.middleware.csrf.CsrfViewMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
try:
    import whitenoise
except ImportError:
    pass
else:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
ROOT_URLCONF = 'trezo_site.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR/'core'/'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request']}}]
WSGI_APPLICATION = 'trezo_site.wsgi.application'
ASGI_APPLICATION = 'trezo_site.asgi.application'
DATABASES = {'default': {'ENGINE': os.environ.get('POSTGRES_ENGINE', 'django.db.backends.postgresql'),
    'NAME': os.environ.get('POSTGRES_DB', 'sklad'), 'USER': os.environ.get('POSTGRES_USER', 'sklad'),
    'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''), 'HOST': os.environ.get('POSTGRES_HOST', 'db'),
    'PORT': os.environ.get('POSTGRES_PORT', '5432')}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR/'core'/'static']
STATIC_ROOT = BASE_DIR/'staticfiles'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_SSL_REDIRECT = flag('DJANGO_SECURE_SSL_REDIRECT')
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = flag('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS')
SECURE_HSTS_PRELOAD = flag('DJANGO_SECURE_HSTS_PRELOAD')
CSRF_COOKIE_SECURE = flag('DJANGO_CSRF_COOKIE_SECURE')
CSRF_TRUSTED_ORIGINS = os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').replace(',', ' ').split()
if flag('DJANGO_SECURE_PROXY_SSL_HEADER'):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = flag('DJANGO_USE_X_FORWARDED_HOST')
SKLAD_WINDOWS_FILE = os.environ.get('SKLAD_WINDOWS_FILE', '')
SKLAD_ANDROID_FILE = os.environ.get('SKLAD_ANDROID_FILE', '')
SKLAD_PAYMENTS_ENABLED = flag('SKLAD_PAYMENTS_ENABLED')
SKLAD_TRUST_PROXY_IP = flag('SKLAD_TRUST_PROXY_IP')
SKLAD_LICENSE_PRIVATE_KEY_FILE = os.environ.get('SKLAD_LICENSE_PRIVATE_KEY_FILE', '')
YOOKASSA_SHOP_ID = os.environ.get('YOOKASSA_SHOP_ID', '')
YOOKASSA_SECRET_KEY = os.environ.get('YOOKASSA_SECRET_KEY', '')
YOOKASSA_RETURN_URL = os.environ.get('YOOKASSA_RETURN_URL', '')
YOOKASSA_VAT_CODE = int(os.environ.get('YOOKASSA_VAT_CODE', '1'))
