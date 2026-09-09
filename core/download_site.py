"""Public download-only site. Legacy data and licensing remain intact."""
from pathlib import Path
from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import render, redirect
from django.urls import path
from django.views.decorators.http import require_GET, require_safe
from . import desktop_licensing


def package(platform):
    defaults = {'windows': 'SKlad.exe', 'android': 'SKlad.apk'}
    if platform not in defaults:
        raise Http404
    configured = getattr(settings, 'SKLAD_' + platform.upper() + '_FILE', '')
    return Path(configured) if configured else settings.BASE_DIR / 'downloads' / defaults[platform]


@require_GET
def home(request):
    return render(request, 'downloads/home.html', {
        'windows_ready': package('windows').is_file(),
        'android_ready': package('android').is_file(),
    })


@require_safe
def download(request, platform):
    source = package(platform)
    try:
        stream = source.open('rb')
    except OSError:
        raise Http404('Сборка пока не опубликована')
    response = FileResponse(stream, as_attachment=True, filename='SKlad' + source.suffix,
                            content_type='application/octet-stream')
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'no-cache'
    return response


@require_GET
def legacy(request, **kwargs):
    return redirect('core:landing')


urlpatterns = [
    path('', home, name='landing'),
    path('download/<str:platform>/', download, name='download'),
    path('desktop/purchase/', desktop_licensing.purchase, name='desktop-purchase'),
    path('desktop/status/', desktop_licensing.status, name='desktop-status'),
    path('desktop/payment/result/', desktop_licensing.payment_result, name='desktop-payment-result'),
]
