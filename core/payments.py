"""Provider adapter for perpetual application licenses."""
from django.conf import settings

def provider():
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise RuntimeError('Payment provider is not configured')
    from yookassa import Configuration, Payment
    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY
    return Payment

def _create_yookassa_payment(payload, idempotence_key):
    return provider().create(payload, idempotence_key)

def _fetch_yookassa_payment(payment_id):
    return provider().find_one(payment_id)

def _nested_value(value, *keys, default=''):
    current = value
    for key in keys:
        current = current.get(key, default) if isinstance(current, dict) else getattr(current, key, default)
        if current is default:
            return default
    return current

def _confirmation_url(response):
    return str(_nested_value(response, 'confirmation', 'confirmation_url') or '')
