from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import ArchiveFile, ArchiveState, SubscriptionHistory, SubscriptionPayment, SubscriptionPlan, UserSubscription


DEFAULT_PLANS = {
    SubscriptionPlan.Code.FREE: {
        'name': 'Free',
        'description': 'Basic account features.',
        'archive_limit': 100,
        'active_auction_limit': 3,
        'is_paid': False,
        'sort_order': 10,
    },
    SubscriptionPlan.Code.PLUS: {
        'name': 'Plus',
        'description': 'Expanded archive and auction limits.',
        'archive_limit': 20000,
        'active_auction_limit': 20,
        'monthly_price': Decimal('99.00'),
        'yearly_price': Decimal('990.00'),
        'is_paid': True,
        'sort_order': 20,
    },
    SubscriptionPlan.Code.PRO: {
        'name': 'Pro',
        'description': 'Professional archive and auction limits.',
        'archive_limit': None,
        'active_auction_limit': 100,
        'monthly_price': Decimal('199.00'),
        'yearly_price': Decimal('1990.00'),
        'is_paid': True,
        'sort_order': 30,
    },
}

PAID_PERIODS = {UserSubscription.BillingPeriod.MONTH, UserSubscription.BillingPeriod.YEAR}
PAID_PLAN_CODES = {SubscriptionPlan.Code.PLUS, SubscriptionPlan.Code.PRO}
PAYMENT_PRICE_TABLE = {
    (SubscriptionPlan.Code.PLUS, UserSubscription.BillingPeriod.MONTH): Decimal('99.00'),
    (SubscriptionPlan.Code.PLUS, UserSubscription.BillingPeriod.YEAR): Decimal('990.00'),
    (SubscriptionPlan.Code.PRO, UserSubscription.BillingPeriod.MONTH): Decimal('199.00'),
    (SubscriptionPlan.Code.PRO, UserSubscription.BillingPeriod.YEAR): Decimal('1990.00'),
}
ARCHIVE_LIMIT_ERROR = (
    'Достигнут лимит архива для вашего тарифа. '
    'Перейдите на другой тариф или удалите ненужные объекты'
)
PAYMENT_UNAVAILABLE_MESSAGE = 'Оплата временно недоступна'
PAYMENT_EMAIL_REQUIRED_MESSAGE = 'Для получения чека укажите электронную почту в настройках аккаунта.'
PAYMENT_GENERIC_ERROR_MESSAGE = 'Не удалось создать платеж. Попробуйте позже.'

logger = logging.getLogger(__name__)


class SubscriptionLimitError(ValidationError):
    pass


class PaymentUnavailable(ValidationError):
    pass


class PaymentGatewayError(ValidationError):
    pass


class PaymentReceiptError(ValidationError):
    """Raised when a receipt cannot be built (e.g. the user has no email)."""
    pass


@dataclass(frozen=True)
class CheckoutIntent:
    provider: str
    tariff_code: str
    period: str
    payment_uuid: str
    subscription_id: int | None
    confirmation_url: str


@dataclass(frozen=True)
class ArchiveLimitSnapshot:
    subscription: UserSubscription
    tariff: SubscriptionPlan
    archive_limit: int | None
    archive_used: int
    archive_remaining: int | None

    @property
    def is_unlimited(self) -> bool:
        return self.archive_limit is None


@dataclass(frozen=True)
class PaymentProcessingResult:
    payment: SubscriptionPayment | None
    status: str
    activated: bool = False
    message: str = ''


def seed_default_plans() -> None:
    for code, defaults in DEFAULT_PLANS.items():
        SubscriptionPlan.objects.update_or_create(code=code, defaults=defaults)


def get_free_plan() -> SubscriptionPlan:
    plan, _ = SubscriptionPlan.objects.get_or_create(
        code=SubscriptionPlan.Code.FREE,
        defaults=DEFAULT_PLANS[SubscriptionPlan.Code.FREE],
    )
    return plan


def get_active_subscription(user, *, refresh: bool = True) -> UserSubscription:
    if refresh:
        expire_due_subscriptions(user=user)
    subscription = (
        UserSubscription.objects.select_related('tariff')
        .filter(user=user, status=UserSubscription.Status.ACTIVE)
        .order_by('-starts_at', '-id')
        .first()
    )
    if subscription is not None:
        return subscription
    return ensure_free_subscription(user)


def ensure_free_subscription(user) -> UserSubscription:
    free_plan = get_free_plan()
    active = UserSubscription.objects.filter(user=user, status=UserSubscription.Status.ACTIVE).first()
    if active is not None:
        return active
    subscription = UserSubscription.objects.create(
        user=user,
        tariff=free_plan,
        starts_at=timezone.now(),
        expires_at=None,
        status=UserSubscription.Status.ACTIVE,
        billing_period=UserSubscription.BillingPeriod.FREE,
        auto_renew=False,
    )
    SubscriptionHistory.objects.create(
        user=user,
        subscription=subscription,
        to_plan=free_plan,
        to_status=UserSubscription.Status.ACTIVE,
        billing_period=UserSubscription.BillingPeriod.FREE,
        reason='free_assigned',
    )
    return subscription


def _period_end(starts_at, billing_period: str):
    if billing_period == UserSubscription.BillingPeriod.MONTH:
        return _add_calendar_months(starts_at, 1)
    if billing_period == UserSubscription.BillingPeriod.YEAR:
        return _add_calendar_months(starts_at, 12)
    return None


def _add_calendar_months(value, months: int):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


@transaction.atomic
def activate_subscription(
    user,
    plan: SubscriptionPlan | str,
    *,
    billing_period: str,
    auto_renew: bool = False,
    starts_at=None,
    provider: str = '',
    provider_payment_id: str = '',
    reason: str = 'activated',
) -> UserSubscription:
    if isinstance(plan, str):
        plan = SubscriptionPlan.objects.get(code=plan)
    if plan.is_paid and billing_period not in PAID_PERIODS:
        raise ValidationError({'billing_period': 'Paid plans require month or year period.'})
    if not plan.is_paid and billing_period != UserSubscription.BillingPeriod.FREE:
        raise ValidationError({'billing_period': 'Free plan uses free period.'})

    starts_at = starts_at or timezone.now()
    expires_at = _period_end(starts_at, billing_period)
    current = UserSubscription.objects.select_for_update().filter(
        user=user,
        status=UserSubscription.Status.ACTIVE,
    ).select_related('tariff').first()
    previous_plan = current.tariff if current else None
    previous_status = current.status if current else ''
    if current is not None:
        current.status = UserSubscription.Status.CANCELED
        current.auto_renew = False
        current.save(update_fields=['status', 'auto_renew', 'updated_at'])
        SubscriptionHistory.objects.create(
            user=user,
            subscription=current,
            from_plan=current.tariff,
            from_status=UserSubscription.Status.ACTIVE,
            to_status=UserSubscription.Status.CANCELED,
            billing_period=current.billing_period,
            reason=f'{reason}_previous_cancelled',
        )

    subscription = UserSubscription.objects.create(
        user=user,
        tariff=plan,
        starts_at=starts_at,
        expires_at=expires_at,
        last_successful_payment=starts_at if plan.is_paid else None,
        status=UserSubscription.Status.ACTIVE,
        billing_period=billing_period,
        auto_renew=auto_renew,
        provider=provider,
        provider_payment_id=provider_payment_id,
    )
    SubscriptionHistory.objects.create(
        user=user,
        subscription=subscription,
        from_plan=previous_plan,
        to_plan=plan,
        from_status=previous_status,
        to_status=UserSubscription.Status.ACTIVE,
        billing_period=billing_period,
        reason=reason,
    )
    return subscription


@transaction.atomic
def create_pending_subscription(user, plan: SubscriptionPlan | str, *, billing_period: str, auto_renew: bool = False):
    payment = create_subscription_payment(user, plan, period=billing_period)
    return payment


@transaction.atomic
def create_subscription_payment(user, plan: SubscriptionPlan | str, *, period: str) -> SubscriptionPayment:
    if isinstance(plan, str):
        plan = SubscriptionPlan.objects.get(code=plan)
    if not plan.is_paid:
        raise ValidationError({'plan': 'Free plan does not need payment.'})
    if period not in PAID_PERIODS:
        raise ValidationError({'billing_period': 'Choose month or year period.'})
    return _create_local_subscription_payment(user, plan, period)


def yookassa_is_configured() -> bool:
    return bool(settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY and settings.YOOKASSA_RETURN_URL)


def payment_unavailable_error() -> PaymentUnavailable:
    return PaymentUnavailable({'payment': [PAYMENT_UNAVAILABLE_MESSAGE]})


def _payment_amount(plan: SubscriptionPlan, period: str) -> Decimal:
    try:
        return PAYMENT_PRICE_TABLE[(plan.code, period)]
    except KeyError as exc:
        raise ValidationError({'amount': 'Tariff price is not configured.'}) from exc


def _idempotence_key(payment: SubscriptionPayment) -> str:
    return f'savetory-subscription-{payment.internal_uuid}'


def _local_payment_metadata(user, plan: SubscriptionPlan, period: str, payment_uuid: str) -> dict:
    return {
        'internal_payment_id': payment_uuid,
        'user_id': str(user.pk),
        'plan': plan.code,
        'period': period,
    }


def _create_local_subscription_payment(user, plan: SubscriptionPlan, period: str) -> SubscriptionPayment:
    payment = SubscriptionPayment(
        user=user,
        tariff=plan,
        period=period,
        amount=_payment_amount(plan, period),
        currency='RUB',
        status=SubscriptionPayment.Status.CREATED,
    )
    payment.idempotence_key = _idempotence_key(payment)
    payment.metadata = _local_payment_metadata(user, plan, period, str(payment.internal_uuid))
    payment.save()
    logger.info(
        'Subscription local payment created: payment_uuid=%s user_id=%s tariff=%s period=%s amount=%s',
        payment.internal_uuid,
        user.pk,
        plan.code,
        period,
        payment.amount,
    )
    return payment


def _period_description(period: str) -> str:
    return '1 месяц' if period == UserSubscription.BillingPeriod.MONTH else '1 год'


def payment_description(plan: SubscriptionPlan, period: str) -> str:
    names = {
        SubscriptionPlan.Code.PLUS: 'Плюс',
        SubscriptionPlan.Code.PRO: 'Про',
    }
    return f"Подписка {names.get(plan.code, plan.name)} на {_period_description(period)}, savetory.ru"


def _payment_return_url(payment: SubscriptionPayment) -> str:
    base = settings.YOOKASSA_RETURN_URL
    payment_uuid = str(payment.internal_uuid)
    if '{payment_uuid}' in base:
        return base.replace('{payment_uuid}', payment_uuid)
    separator = '&' if '?' in base else '?'
    return f'{base}{separator}payment={payment_uuid}'

def _format_decimal(value: Decimal) -> str:
    return f'{Decimal(value):.2f}'


def customer_email(user) -> str:
    """Return the user's email for the receipt, or raise a user-facing error.

    A receipt (54-ФЗ) is mandatory for YooKassa, and the receipt requires a
    customer contact. Without an email we must not contact YooKassa at all.
    """
    email = (getattr(user, 'email', '') or '').strip()
    if not email:
        raise PaymentReceiptError({'email': [PAYMENT_EMAIL_REQUIRED_MESSAGE]})
    return email


def _build_receipt(user, payment: SubscriptionPayment) -> dict:
    amount_value = _format_decimal(payment.amount)
    return {
        'customer': {
            'email': customer_email(user),
        },
        'items': [
            {
                'description': payment_description(payment.tariff, payment.period),
                'quantity': '1.00',
                'amount': {
                    # Must match payment.amount exactly (single item, quantity 1).
                    'value': amount_value,
                    'currency': 'RUB',
                },
                'vat_code': settings.YOOKASSA_VAT_CODE,
                'payment_subject': 'service',
                'payment_mode': settings.YOOKASSA_PAYMENT_MODE,
            }
        ],
    }


def _build_yookassa_payload(user, payment: SubscriptionPayment) -> dict:
    description = payment_description(payment.tariff, payment.period)
    payload = {
        'amount': {
            'value': _format_decimal(payment.amount),
            'currency': 'RUB',
        },
        'capture': True,
        'confirmation': {
            'type': 'redirect',
            'return_url': _payment_return_url(payment),
        },
        'description': description,
        'receipt': _build_receipt(user, payment),
        'metadata': {
            'internal_payment_id': str(payment.internal_uuid),
            'user_id': str(user.pk),
            'plan': payment.tariff.code,
            'period': payment.period,
        },
    }
    return payload


def _response_value(response, key: str, default=''):
    if isinstance(response, dict):
        return response.get(key, default)
    return getattr(response, key, default)


def _confirmation_url(response) -> str:
    confirmation = _response_value(response, 'confirmation', None)
    if isinstance(confirmation, dict):
        return str(confirmation.get('confirmation_url') or '')
    return str(getattr(confirmation, 'confirmation_url', '') or '')


def _safe_yookassa_error_fields(exc) -> dict:
    """Extract only the safe, non-sensitive fields from a YooKassa API error.

    Never returns secrets, credentials or customer data — only the error
    ``code``, ``parameter`` and ``description`` provided by YooKassa.
    """
    content = getattr(exc, 'content', None)
    if not isinstance(content, dict):
        args = getattr(exc, 'args', None)
        content = args[0] if args and isinstance(args[0], dict) else {}
    return {
        'code': content.get('code', ''),
        'parameter': content.get('parameter', ''),
        'description': content.get('description', ''),
    }


def _create_yookassa_payment(payload: dict, idempotence_key: str):
    try:
        from yookassa import Configuration, Payment
    except ImportError as exc:  # pragma: no cover - exercised when dependency is missing in env
        raise payment_unavailable_error() from exc

    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY
    try:
        return Payment.create(payload, idempotence_key)
    except Exception as exc:
        fields = _safe_yookassa_error_fields(exc)
        logger.warning(
            'YooKassa API create error: type=%s code=%s parameter=%s description=%s',
            exc.__class__.__name__,
            fields['code'],
            fields['parameter'],
            fields['description'],
        )
        raise


def _fetch_yookassa_payment(payment_id: str):
    if not yookassa_is_configured():
        raise payment_unavailable_error()
    try:
        from yookassa import Configuration, Payment
    except ImportError as exc:  # pragma: no cover
        raise payment_unavailable_error() from exc

    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY
    try:
        return Payment.find_one(payment_id)
    except Exception as exc:
        logger.warning('YooKassa API fetch error: payment_id=%s error=%s', payment_id, exc.__class__.__name__)
        raise


def _local_payment_status(value: str) -> str:
    if value in SubscriptionPayment.Status.values:
        return value
    return SubscriptionPayment.Status.PENDING


def _nested_value(value, *keys, default=''):
    current = value
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            current = getattr(current, key, default)
        if current is default:
            return default
    return current


def _remote_metadata(remote) -> dict:
    metadata = _response_value(remote, 'metadata', {}) or {}
    if isinstance(metadata, dict):
        return metadata
    return dict(metadata)


def _remote_amount(remote) -> Decimal:
    return Decimal(str(_nested_value(remote, 'amount', 'value')))


def _remote_currency(remote) -> str:
    return str(_nested_value(remote, 'amount', 'currency')).upper()


def _remote_status(remote) -> str:
    return str(_response_value(remote, 'status', '') or '')


def _remote_paid(remote) -> bool:
    return bool(_response_value(remote, 'paid', False))


def _validate_remote_payment(payment: SubscriptionPayment, remote) -> list[str]:
    errors: list[str] = []
    metadata = _remote_metadata(remote)
    remote_id = str(_response_value(remote, 'id', '') or '')
    if remote_id != payment.yookassa_payment_id:
        errors.append('payment_id')
    if _remote_currency(remote) != 'RUB':
        errors.append('currency')
    try:
        if _remote_amount(remote) != Decimal(payment.amount):
            errors.append('amount')
    except Exception:
        errors.append('amount')
    internal_payment_id = metadata.get('internal_payment_id') or metadata.get('payment_uuid') or ''
    if internal_payment_id and str(internal_payment_id) != str(payment.internal_uuid):
        errors.append('internal_payment_id')
    if metadata.get('user_id') and str(metadata.get('user_id')) != str(payment.user_id):
        errors.append('user')
    plan_code = metadata.get('plan') or metadata.get('tariff_code') or ''
    if plan_code and str(plan_code) != payment.tariff.code:
        errors.append('plan')
    if metadata.get('period') and str(metadata.get('period')) != payment.period:
        errors.append('period')
    return errors


def _find_payment_for_remote(remote) -> SubscriptionPayment | None:
    metadata = _remote_metadata(remote)
    payment_uuid = str(metadata.get('internal_payment_id') or metadata.get('payment_uuid') or '')
    qs = SubscriptionPayment.objects.select_for_update().select_related('user', 'tariff')
    if payment_uuid:
        try:
            return qs.get(internal_uuid=payment_uuid)
        except (SubscriptionPayment.DoesNotExist, ValueError, ValidationError):
            return None
    remote_id = str(_response_value(remote, 'id', '') or '')
    if not remote_id:
        return None
    return qs.filter(yookassa_payment_id=remote_id).first()


def _apply_verified_remote_payment(payment: SubscriptionPayment, remote, *, now=None) -> PaymentProcessingResult:
    remote_status = _remote_status(remote)
    local_status = _local_payment_status(remote_status)

    if payment.subscription_activated:
        logger.info(
            'Repeated YooKassa payment processing skipped: payment_uuid=%s payment_id=%s status=%s',
            payment.internal_uuid,
            payment.yookassa_payment_id,
            payment.status,
        )
        return PaymentProcessingResult(payment=payment, status=payment.status, activated=False, message='Already processed.')

    validation_errors = _validate_remote_payment(payment, remote)
    if validation_errors:
        logger.warning(
            'YooKassa payment validation mismatch: payment_uuid=%s payment_id=%s fields=%s',
            payment.internal_uuid,
            payment.yookassa_payment_id,
            ','.join(validation_errors),
        )
        payment.status = SubscriptionPayment.Status.FAILED
        payment.error_message = 'Payment validation failed: ' + ','.join(validation_errors)
        payment.save(update_fields=['status', 'error_message', 'updated_at'])
        return PaymentProcessingResult(payment=payment, status='error', message='Payment validation failed.')

    if remote_status == SubscriptionPayment.Status.CANCELED:
        logger.info(
            'YooKassa payment canceled: payment_uuid=%s payment_id=%s user_id=%s',
            payment.internal_uuid,
            payment.yookassa_payment_id,
            payment.user_id,
        )
        payment.status = SubscriptionPayment.Status.CANCELED
        payment.save(update_fields=['status', 'updated_at'])
        return PaymentProcessingResult(payment=payment, status=SubscriptionPayment.Status.CANCELED)

    if remote_status != SubscriptionPayment.Status.SUCCEEDED:
        payment.status = local_status
        payment.save(update_fields=['status', 'updated_at'])
        return PaymentProcessingResult(payment=payment, status=local_status)

    if not _remote_paid(remote):
        payment.status = SubscriptionPayment.Status.PENDING
        payment.save(update_fields=['status', 'updated_at'])
        return PaymentProcessingResult(payment=payment, status=SubscriptionPayment.Status.PENDING, message='Payment is not marked as paid.')

    payment.status = SubscriptionPayment.Status.SUCCEEDED
    payment.paid_at = now or timezone.now()
    subscription = _activate_paid_subscription_from_payment(payment, now=payment.paid_at)
    if subscription is None:
        payment.error_message = 'Active Pro subscription cannot be downgraded to Plus before expiration.'
        payment.save(update_fields=['status', 'paid_at', 'error_message', 'updated_at'])
        return PaymentProcessingResult(payment=payment, status='blocked', activated=False, message=payment.error_message)

    payment.subscription_activated = True
    payment.error_message = ''
    payment.save(update_fields=['status', 'paid_at', 'subscription_activated', 'error_message', 'updated_at'])
    return PaymentProcessingResult(payment=payment, status=SubscriptionPayment.Status.SUCCEEDED, activated=True)


def _activate_paid_subscription_from_payment(payment: SubscriptionPayment, *, now=None) -> UserSubscription | None:
    now = now or timezone.now()
    expire_due_subscriptions(user=payment.user, now=now)
    current = (
        UserSubscription.objects.select_for_update()
        .filter(user=payment.user, status=UserSubscription.Status.ACTIVE)
        .select_related('tariff')
        .first()
    )
    if (
        current
        and current.tariff.code == SubscriptionPlan.Code.PRO
        and payment.tariff.code == SubscriptionPlan.Code.PLUS
        and (current.expires_at is None or current.expires_at > now)
    ):
        logger.info(
            'Subscription downgrade blocked: payment_uuid=%s user_id=%s current_tariff=%s requested_tariff=%s',
            payment.internal_uuid,
            payment.user_id,
            current.tariff.code,
            payment.tariff.code,
        )
        return None

    if current and current.tariff_id == payment.tariff_id and current.tariff.is_paid and current.expires_at and current.expires_at > now:
        previous_expires_at = current.expires_at
        current.expires_at = _period_end(current.expires_at, payment.period)
        current.billing_period = payment.period
        current.last_successful_payment = now
        current.provider = 'yookassa'
        current.provider_payment_id = payment.yookassa_payment_id
        current.save(update_fields=[
            'expires_at',
            'billing_period',
            'last_successful_payment',
            'provider',
            'provider_payment_id',
            'updated_at',
        ])
        SubscriptionHistory.objects.create(
            user=payment.user,
            subscription=current,
            from_plan=payment.tariff,
            to_plan=payment.tariff,
            from_status=UserSubscription.Status.ACTIVE,
            to_status=UserSubscription.Status.ACTIVE,
            billing_period=payment.period,
            reason='payment_extended',
            metadata={'previous_expires_at': previous_expires_at.isoformat(), 'payment_uuid': str(payment.internal_uuid)},
        )
        logger.info(
            'Subscription extended: payment_uuid=%s user_id=%s subscription_id=%s tariff=%s previous_expires_at=%s expires_at=%s',
            payment.internal_uuid,
            payment.user_id,
            current.pk,
            payment.tariff.code,
            previous_expires_at,
            current.expires_at,
        )
        return current

    previous_plan = current.tariff if current else None
    previous_status = current.status if current else ''
    if current is not None:
        current.status = UserSubscription.Status.CANCELED
        current.auto_renew = False
        current.save(update_fields=['status', 'auto_renew', 'updated_at'])
        SubscriptionHistory.objects.create(
            user=payment.user,
            subscription=current,
            from_plan=current.tariff,
            from_status=UserSubscription.Status.ACTIVE,
            to_status=UserSubscription.Status.CANCELED,
            billing_period=current.billing_period,
            reason='payment_previous_cancelled',
            metadata={'payment_uuid': str(payment.internal_uuid)},
        )

    subscription = UserSubscription.objects.create(
        user=payment.user,
        tariff=payment.tariff,
        starts_at=now,
        expires_at=_period_end(now, payment.period),
        last_successful_payment=now,
        status=UserSubscription.Status.ACTIVE,
        billing_period=payment.period,
        auto_renew=False,
        provider='yookassa',
        provider_payment_id=payment.yookassa_payment_id,
    )
    SubscriptionHistory.objects.create(
        user=payment.user,
        subscription=subscription,
        from_plan=previous_plan,
        to_plan=payment.tariff,
        from_status=previous_status,
        to_status=UserSubscription.Status.ACTIVE,
        billing_period=payment.period,
        reason='payment_activated',
        metadata={'payment_uuid': str(payment.internal_uuid)},
    )
    logger.info(
        'Subscription activated: payment_uuid=%s user_id=%s subscription_id=%s tariff=%s expires_at=%s',
        payment.internal_uuid,
        payment.user_id,
        subscription.pk,
        payment.tariff.code,
        subscription.expires_at,
    )
    return subscription


@transaction.atomic
def process_yookassa_payment(payment_id: str, *, now=None) -> PaymentProcessingResult:
    remote = _fetch_yookassa_payment(payment_id)
    payment = _find_payment_for_remote(remote)
    if payment is None:
        return PaymentProcessingResult(payment=None, status='error', message='Local payment was not found.')
    return _apply_verified_remote_payment(payment, remote, now=now)


@transaction.atomic
def refresh_yookassa_payment_status(payment: SubscriptionPayment, *, now=None) -> PaymentProcessingResult:
    if not payment.yookassa_payment_id:
        return PaymentProcessingResult(payment=payment, status=payment.status)

    remote = _fetch_yookassa_payment(payment.yookassa_payment_id)
    payment = (
        SubscriptionPayment.objects.select_for_update()
        .select_related('user', 'tariff')
        .get(pk=payment.pk)
    )
    return _apply_verified_remote_payment(payment, remote, now=now)


def _find_reusable_payment(user, plan: SubscriptionPlan, period: str) -> SubscriptionPayment | None:
    return (
        SubscriptionPayment.objects.select_for_update()
        .filter(
            user=user,
            tariff=plan,
            period=period,
            subscription_activated=False,
            status__in=[SubscriptionPayment.Status.CREATED, SubscriptionPayment.Status.PENDING],
        )
        .order_by('-created_at', '-id')
        .first()
    )


@transaction.atomic
def expire_due_subscriptions(*, user=None, now=None) -> int:
    now = now or timezone.now()
    qs = UserSubscription.objects.select_for_update().filter(
        status=UserSubscription.Status.ACTIVE,
        tariff__is_paid=True,
        expires_at__isnull=False,
        expires_at__lte=now,
    ).select_related('user', 'tariff')
    if user is not None:
        qs = qs.filter(user=user)

    expired_count = 0
    for subscription in qs:
        old_plan = subscription.tariff
        subscription.status = UserSubscription.Status.EXPIRED
        subscription.auto_renew = False
        subscription.save(update_fields=['status', 'auto_renew', 'updated_at'])
        SubscriptionHistory.objects.create(
            user=subscription.user,
            subscription=subscription,
            from_plan=old_plan,
            from_status=UserSubscription.Status.ACTIVE,
            to_status=UserSubscription.Status.EXPIRED,
            billing_period=subscription.billing_period,
            reason='expired',
        )
        ensure_free_subscription(subscription.user)
        expired_count += 1
    return expired_count


def archive_state_file_count(data) -> int:
    if not isinstance(data, dict):
        return 0
    rubrics = data.get('rubrics')
    if not isinstance(rubrics, list):
        return 0
    total = 0
    for rubric in rubrics:
        if not isinstance(rubric, dict):
            continue
        files = rubric.get('files')
        if isinstance(files, list):
            total += len([item for item in files if isinstance(item, dict)])
    return total


def archive_usage(user) -> int:
    db_count = ArchiveFile.objects.filter(owner=user).count()
    state = ArchiveState.objects.filter(user=user).first()
    state_count = archive_state_file_count(state.data if state else None)
    return max(db_count, state_count)


def active_auction_usage(user) -> int:
    from market.models import Listing

    return Listing.objects.filter(
        seller=user,
        type=Listing.Type.AUCTION,
        status__in=Listing.LIVE_STATUSES,
    ).count()


def subscription_limits(user) -> dict:
    snapshot = archive_limit_snapshot(user)
    plan = snapshot.tariff
    return {
        'subscription': snapshot.subscription,
        'plan': plan,
        'archive_limit': snapshot.archive_limit,
        'active_auction_limit': plan.active_auction_limit,
        'archive_used': snapshot.archive_used,
        'archive_remaining': snapshot.archive_remaining,
        'active_auction_used': active_auction_usage(user),
        'archive_limit_label': archive_limit_label(snapshot.archive_limit),
    }


def current_tariff(user) -> SubscriptionPlan:
    return get_active_subscription(user).tariff


def archive_limit_snapshot(user) -> ArchiveLimitSnapshot:
    subscription = get_active_subscription(user)
    tariff = subscription.tariff
    limit = tariff.archive_limit
    used = archive_usage(user)
    remaining = None if limit is None else max(limit - used, 0)
    return ArchiveLimitSnapshot(
        subscription=subscription,
        tariff=tariff,
        archive_limit=limit,
        archive_used=used,
        archive_remaining=remaining,
    )


def archive_limit(user) -> int | None:
    return archive_limit_snapshot(user).archive_limit


def archive_remaining(user) -> int | None:
    return archive_limit_snapshot(user).archive_remaining


def can_create_archive_file(user, *, incoming_count: int = 1) -> bool:
    snapshot = archive_limit_snapshot(user)
    if snapshot.is_unlimited:
        return True
    return snapshot.archive_used + incoming_count <= snapshot.archive_limit


def assert_can_create_archive_file(user, *, incoming_count: int = 1) -> None:
    snapshot = archive_limit_snapshot(user)
    if snapshot.is_unlimited:
        return
    if snapshot.archive_used + incoming_count > snapshot.archive_limit:
        logger.info(
            'Archive limit reached: user_id=%s used=%s incoming=%s limit=%s tariff=%s',
            user.pk,
            snapshot.archive_used,
            incoming_count,
            snapshot.archive_limit,
            snapshot.tariff.code,
        )
        raise SubscriptionLimitError({'archive': [ARCHIVE_LIMIT_ERROR]})


def assert_archive_state_within_limit(user, new_state: dict, old_state: dict | None = None) -> None:
    old_count = archive_state_file_count(old_state)
    new_count = archive_state_file_count(new_state)
    db_count = ArchiveFile.objects.filter(owner=user).count()
    new_effective = max(db_count, new_count)
    snapshot = archive_limit_snapshot(user)
    if snapshot.is_unlimited:
        return
    if new_count > old_count and new_effective > snapshot.archive_limit:
        logger.info(
            'Archive limit reached in state update: user_id=%s old_count=%s new_count=%s effective=%s limit=%s tariff=%s',
            user.pk,
            old_count,
            new_count,
            new_effective,
            snapshot.archive_limit,
            snapshot.tariff.code,
        )
        raise SubscriptionLimitError({'archive': [ARCHIVE_LIMIT_ERROR]})


def assert_can_create_active_auction(user, *, exclude_listing_id=None) -> None:
    from market.models import Listing

    subscription = get_active_subscription(user)
    qs = Listing.objects.filter(
        seller=user,
        type=Listing.Type.AUCTION,
        status__in=Listing.LIVE_STATUSES,
    )
    if exclude_listing_id:
        qs = qs.exclude(pk=exclude_listing_id)
    used = qs.count()
    limit = subscription.tariff.active_auction_limit
    if used >= limit:
        raise SubscriptionLimitError({
            'subscription': [
                f"Active auction limit reached for {subscription.tariff.name}: {used} of {limit} active auctions."
            ]
        })


def archive_limit_label(limit) -> str:
    if limit is None:
        return 'Без ограничений'
    return f'{int(limit):,}'.replace(',', ' ')


def amount_label(price) -> str:
    if price is None:
        return ''
    value = Decimal(price)
    if value == value.to_integral_value():
        return f'{int(value):,}'.replace(',', ' ')
    return f'{value:,.2f}'.replace(',', ' ')


def button_price_label(price) -> str:
    amount = amount_label(price)
    return f'{amount} ₽' if amount else ''


def price_label(price, period: str) -> str:
    amount = amount_label(price)
    return f'{amount} ₽/{period}' if amount else ''


def available_plan_cards() -> list[dict]:
    return [
        {
            'code': plan.code,
            'name': plan.name,
            'description': plan.description,
            'archive_limit': plan.archive_limit,
            'archive_limit_label': archive_limit_label(plan.archive_limit),
            'active_auction_limit': plan.active_auction_limit,
            'is_paid': plan.is_paid,
            'monthly_price': plan.monthly_price,
            'yearly_price': plan.yearly_price,
            'monthly_amount_label': amount_label(plan.monthly_price),
            'yearly_amount_label': amount_label(plan.yearly_price),
            'monthly_price_label': price_label(plan.monthly_price, 'месяц'),
            'yearly_price_label': price_label(plan.yearly_price, 'год'),
            'monthly_button_label': button_price_label(plan.monthly_price),
            'yearly_button_label': button_price_label(plan.yearly_price),
        }
        for plan in SubscriptionPlan.objects.filter(is_active=True).order_by('sort_order', 'id')
    ]


class BillingGateway:
    provider = 'stub'

    def create_checkout(self, user, plan: SubscriptionPlan, billing_period: str, *, auto_renew: bool = False) -> CheckoutIntent:
        raise payment_unavailable_error()


class YooKassaGateway(BillingGateway):
    provider = 'yookassa'

    def create_checkout(self, user, plan: SubscriptionPlan, billing_period: str, *, auto_renew: bool = False) -> CheckoutIntent:
        if not yookassa_is_configured():
            raise payment_unavailable_error()

        # A receipt is mandatory, so an email is required before we touch the DB
        # or contact YooKassa. Raises PaymentReceiptError when it is missing.
        customer_email(user)

        with transaction.atomic():
            payment = _find_reusable_payment(user, plan, billing_period)
            if payment is None:
                payment = _create_local_subscription_payment(user, plan, billing_period)
            else:
                logger.info(
                    'Reusable subscription payment found: payment_uuid=%s user_id=%s tariff=%s period=%s status=%s',
                    payment.internal_uuid,
                    user.pk,
                    plan.code,
                    billing_period,
                    payment.status,
                )

        if payment.confirmation_url:
            return CheckoutIntent(
                provider=self.provider,
                tariff_code=plan.code,
                period=billing_period,
                payment_uuid=str(payment.internal_uuid),
                subscription_id=None,
                confirmation_url=payment.confirmation_url,
            )

        payload = _build_yookassa_payload(user, payment)
        try:
            logger.info(
                'YooKassa payment creation requested: payment_uuid=%s user_id=%s tariff=%s period=%s amount=%s',
                payment.internal_uuid,
                user.pk,
                plan.code,
                billing_period,
                payment.amount,
            )
            response = _create_yookassa_payment(payload, payment.idempotence_key)
        except ValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK errors should not become HTTP 500
            logger.warning(
                'YooKassa payment creation failed: payment_uuid=%s user_id=%s error=%s',
                payment.internal_uuid,
                user.pk,
                exc.__class__.__name__,
            )
            payment.status = SubscriptionPayment.Status.FAILED
            payment.error_message = 'YooKassa payment creation failed.'
            payment.save(update_fields=['status', 'error_message', 'updated_at'])
            raise PaymentGatewayError({'payment': [PAYMENT_GENERIC_ERROR_MESSAGE]}) from exc

        confirmation_url = _confirmation_url(response)
        yookassa_payment_id = str(_response_value(response, 'id', '') or '')
        gateway_status = str(_response_value(response, 'status', SubscriptionPayment.Status.PENDING) or SubscriptionPayment.Status.PENDING)
        status = _local_payment_status(gateway_status)
        if not confirmation_url or not yookassa_payment_id:
            payment.status = SubscriptionPayment.Status.FAILED
            payment.error_message = 'YooKassa response did not contain confirmation URL.'
            payment.save(update_fields=['status', 'error_message', 'updated_at'])
            raise PaymentGatewayError({'payment': [PAYMENT_GENERIC_ERROR_MESSAGE]})

        payment.yookassa_payment_id = yookassa_payment_id
        payment.status = status
        payment.confirmation_url = confirmation_url
        metadata = dict(payment.metadata or {})
        metadata['yookassa_status'] = gateway_status
        payment.metadata = metadata
        payment.save(update_fields=[
            'yookassa_payment_id',
            'status',
            'confirmation_url',
            'metadata',
            'updated_at',
        ])
        logger.info(
            'YooKassa payment created: payment_uuid=%s payment_id=%s user_id=%s status=%s',
            payment.internal_uuid,
            payment.yookassa_payment_id,
            user.pk,
            payment.status,
        )

        return CheckoutIntent(
            provider=self.provider,
            tariff_code=plan.code,
            period=billing_period,
            payment_uuid=str(payment.internal_uuid),
            subscription_id=None,
            confirmation_url=payment.confirmation_url,
        )


def create_checkout_intent(user, plan_code: str, billing_period: str, *, auto_renew: bool = False) -> CheckoutIntent:
    if plan_code not in PAID_PLAN_CODES:
        raise ValidationError({'plan': 'Unknown subscription plan.'})
    if billing_period not in PAID_PERIODS:
        raise ValidationError({'period': 'Choose month or year period.'})
    plan = SubscriptionPlan.objects.get(code=plan_code, is_active=True)
    gateway = YooKassaGateway() if yookassa_is_configured() else BillingGateway()
    return gateway.create_checkout(user, plan, billing_period, auto_renew=auto_renew)


def backfill_free_subscriptions() -> int:
    User = get_user_model()
    count = 0
    for user in User.objects.all().iterator():
        before = UserSubscription.objects.filter(user=user, status=UserSubscription.Status.ACTIVE).exists()
        ensure_free_subscription(user)
        if not before:
            count += 1
    return count
