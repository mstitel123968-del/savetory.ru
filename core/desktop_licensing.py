"""Independent, perpetual desktop purchases. No website account is required."""
import base64
import json
import uuid
from decimal import Decimal
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from .models import DesktopPurchase
from .payments import _create_yookassa_payment, _fetch_yookassa_payment, _nested_value, _confirmation_url


def signing_key():
    key = load_pem_private_key(Path(settings.SKLAD_LICENSE_PRIVATE_KEY_FILE).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Expected Ed25519 key')
    return key


def license_for(order):
    payload = json.dumps({'product': 'sklad-desktop', 'version': 1,
                          'license_id': str(order.pk), 'perpetual': True},
                         separators=(',', ':'), sort_keys=True).encode()
    return {'payload': base64.b64encode(payload).decode(),
            'signature': base64.b64encode(signing_key().sign(payload)).decode()}


def limited(request, scope, maximum):
    # Back this with a shared cache or reverse-proxy rate limit in production.
    key = 'desktop:' + scope + ':' + request.META.get('REMOTE_ADDR', 'unknown')
    if cache.add(key, 1, timeout=60):
        return False
    try:
        return cache.incr(key) > maximum
    except ValueError:
        return False


@csrf_exempt
@require_POST
def purchase(request):
    if limited(request, 'purchase', 5):
        return JsonResponse({'error': 'Слишком много попыток. Подождите минуту.'}, status=429)
    if not settings.SKLAD_PAYMENTS_ENABLED:
        return JsonResponse({'error': 'Покупка ещё не подключена. Попробуйте позже.'}, status=503)
    try:
        signing_key()  # Never charge if this deployment cannot issue a license.
        if len(request.body) > 4096:
            raise ValueError()
        data = json.loads(request.body)
        token = uuid.UUID(data['purchase_code'])
        if token.version != 4:
            raise ValueError()
        email = data['email'].strip().lower()
        validate_email(email)
    except (ValueError, TypeError, KeyError, AttributeError, ValidationError):
        return JsonResponse({'error': 'Укажите корректную почту для чека.'}, status=400)
    except Exception:
        return JsonResponse({'error': 'Покупка временно недоступна.'}, status=503)
    order, _ = DesktopPurchase.objects.get_or_create(id=token, defaults={'email': email})
    if order.email != email:
        return JsonResponse({'error': 'Для этой покупки указана другая почта.'}, status=409)
    if order.status == 'succeeded':
        return JsonResponse({'status': 'succeeded', 'license': license_for(order)})
    if order.status == 'canceled':
        return JsonResponse({'status': 'canceled'})
    if order.payment_id:
        return JsonResponse({'status': order.status, 'checkout_url': order.checkout_url})
    # YooKassa idempotency retention is 24 h. Do not retry an uncertain older charge.
    if (timezone.now() - order.created_at).total_seconds() > 23 * 3600:
        return JsonResponse({'error': 'Срок попытки оплаты истёк. Обратитесь в поддержку перед новой покупкой.'}, status=409)
    try:
        payment = _create_yookassa_payment({
            'amount': {'value': '299.00', 'currency': 'RUB'}, 'capture': True,
            'confirmation': {'type': 'redirect', 'return_url': request.build_absolute_uri('/desktop/payment/result/')},
            'description': 'СКлад — полная версия для Windows, разовая покупка',
            'metadata': {'desktop_order': str(order.pk)},
            'receipt': {'customer': {'email': email}, 'items': [{
                'description': 'СКлад — бессрочная лицензия для Windows', 'quantity': '1.00',
                'amount': {'value': '299.00', 'currency': 'RUB'},
                'vat_code': settings.YOOKASSA_VAT_CODE, 'payment_mode': 'full_payment',
                'payment_subject': 'intellectual_activity'}]},
        }, str(order.pk))
        payment_id = _nested_value(payment, 'id')
        checkout = _confirmation_url(payment)
        if not payment_id or not checkout or _nested_value(payment, 'test', default=True):
            raise ValueError('No production checkout')
        order.payment_id, order.checkout_url = payment_id, checkout
        order.save(update_fields=['payment_id', 'checkout_url'])
        return JsonResponse({'status': 'pending', 'checkout_url': checkout})
    except Exception:
        return JsonResponse({'error': 'Не удалось открыть оплату. Повторите проверку; повторного списания не будет.'}, status=503)


@csrf_exempt
@require_POST
def status(request):
    if limited(request, 'status', 30):
        return JsonResponse({'error': 'Подождите минуту перед следующей проверкой.'}, status=429)
    # The random purchase code is a bearer credential; never place it in a URL.
    try:
        if len(request.body) > 4096:
            raise ValueError()
        order = DesktopPurchase.objects.get(pk=uuid.UUID(json.loads(request.body)['purchase_code']))
    except (ValueError, TypeError, KeyError, AttributeError, DesktopPurchase.DoesNotExist):
        return JsonResponse({'error': 'Покупка не найдена.'}, status=404)
    try:
        if not order.payment_id:
            return JsonResponse({'status': 'pending'})
        payment = _fetch_yookassa_payment(order.payment_id)
        valid = (_nested_value(payment, 'id') == order.payment_id
                 and _nested_value(payment, 'metadata', 'desktop_order') == str(order.pk)
                 and _nested_value(payment, 'amount', 'currency') == 'RUB'
                 and Decimal(_nested_value(payment, 'amount', 'value')) == Decimal('299.00')
                 and not _nested_value(payment, 'test', default=True))
        if not valid:
            raise ValueError('Payment verification failed')
        current = _nested_value(payment, 'status')
        if current == 'succeeded' and _nested_value(payment, 'paid', default=False) is True:
            result = {'status': 'succeeded', 'license': license_for(order)}
            order.status = 'succeeded'
        elif current == 'canceled':
            order.status = 'canceled'
            result = {'status': 'canceled'}
        else:
            result = {'status': 'pending'}
        order.save(update_fields=['status'])
        response = JsonResponse(result)
        response['Cache-Control'] = 'no-store'
        return response
    except Exception:
        return JsonResponse({'error': 'Не удалось проверить оплату. Повторите позже.'}, status=503)


@require_GET
def payment_result(request):
    return HttpResponse('<!doctype html><html lang="ru"><meta charset="utf-8"><title>СКлад</title>'
                        '<h1>Вернитесь в приложение СКлад</h1><p>Нажмите «Проверить оплату». '
                        'Полная версия включится после подтверждения платежа.</p></html>')
