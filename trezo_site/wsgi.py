"""Replaces the Java servlet initializer with Django's WSGI configuration."""
import os

from django.conf import settings
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trezo_site.settings')

application = get_wsgi_application()

if not getattr(settings, 'USE_WHITENOISE', False):
    # Ensure static files are served even when WhiteNoise isn't installed yet.
    application = StaticFilesHandler(application)
