"""Replaces the Java application server bootstrap with Django's ASGI entry point."""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trezo_site.settings')
application = get_asgi_application()
