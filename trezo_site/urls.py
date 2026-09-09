from django.http import HttpResponse
from django.urls import include, path, re_path
from core.download_site import legacy

def robots(request):
    return HttpResponse('User-agent: *\nAllow: /\nDisallow: /desktop/\nDisallow: /download/\n', content_type='text/plain')

urlpatterns = [
    path('robots.txt', robots),
    path('', include(('core.download_site', 'core'), namespace='core')),
    re_path(r'^(?!static/|download/|desktop/).*$', legacy),
]
