from django.http import HttpResponse
from django.urls import include, path, re_path
from core.download_site import legacy
from core.support import inbox

def robots(request):
    return HttpResponse('User-agent: *\nAllow: /\nDisallow: /desktop/\nDisallow: /download/\n', content_type='text/plain')

urlpatterns = [
    path('support', inbox),
    path('support/', include(('core.support', 'support'), namespace='support')),
    path('robots.txt', robots),
    path('', include(('core.download_site', 'core'), namespace='core')),
    re_path(r'^(?!static/|download/|desktop/).*$', legacy),
]
