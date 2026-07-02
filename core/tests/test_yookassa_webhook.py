import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Profile, SubscriptionPayment, SubscriptionPlan, UserSubscription
from core.services import subscriptions
from core import views


YOOKASSA_SETTINGS = {
    'YOOKASSA_SHOP_ID': 'test-shop',
    'YOOKASSA_SECRET_KEY': 'test-secret',
    'YOOKASSA_RETURN_URL': 'https://www.savetory.ru/subscriptions/payment/result/',
}


@override_settings(**YOOKASSA_SETTINGS)
class YooKassaWebhookTests(TestCase):
    def setUp(self):
        subscriptions.seed_default_plans()
        self.user = get_user_model().objects.create_user('payer', email='payer@example.com', password='pass1234')
        self.other = get_user_model().objects.create_user('other', email='other@example.com', password='pass1234')
        Profile.objects.create(user=self.user, terms_version_accepted=settings.TERMS_VERSION)
        Profile.objects.create(user=self.other, terms_version_accepted=settings.TERMS_VERSION)
        self.plus = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PLUS)
        self.pro = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PRO)
        self.factory = RequestFactory()

    def _payment_result_response(self, payment, user):
        request = self.factory.get(reverse('core:payment-result'), data={'payment': str(payment.internal_uuid)})
        request.user = user
        with patch('core.views.render', return_value=HttpResponse('payment result')):
            return views.subscription_payment_result(request)

    def _payment(self, tariff=None, period=SubscriptionPayment.Period.MONTH, amount=None):
        tariff = tariff or self.plus
        if amount is None:
            amount = tariff.monthly_price if period == SubscriptionPayment.Period.MONTH else tariff.yearly_price
        return SubscriptionPayment.objects.create(
            user=self.user,
            tariff=tariff,
            period=period,
            amount=Decimal(amount),
            currency='RUB',
            status=SubscriptionPayment.Status.PENDING,
            yookassa_payment_id=f'yk-{tariff.code}-{period}-{SubscriptionPayment.objects.count() + 1}',
            idempotence_key=f'idem-{SubscriptionPayment.objects.count() + 1}',
            confirmation_url='https://yookassa.example/confirm',
            metadata={'tariff_code': tariff.code, 'period': period},
        )

    def _remote(self, payment, *, status=SubscriptionPayment.Status.SUCCEEDED, value=None, currency='RUB', metadata=None):
        if value is None:
            value = payment.amount
        return {
            'id': payment.yookassa_payment_id,
            'status': status,
            'amount': {'value': f'{Decimal(value):.2f}', 'currency': currency},
            'metadata': metadata or {
                'payment_uuid': str(payment.internal_uuid),
                'user_id': str(payment.user_id),
                'tariff_code': payment.tariff.code,
                'period': payment.period,
            },
        }

    def _webhook(self, payment, event='payment.succeeded'):
        return self.client.post(
            reverse('core:yookassa-webhook'),
            data=json.dumps({'event': event, 'object': {'id': payment.yookassa_payment_id}}),
            content_type='application/json',
        )

    def test_succeeded_webhook_activates_subscription(self):
        payment = self._payment()

        with patch('core.services.subscriptions._fetch_yookassa_payment', return_value=self._remote(payment)):
            response = self._webhook(payment)

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertTrue(payment.subscription_activated)
        active = UserSubscription.objects.get(user=self.user, status=UserSubscription.Status.ACTIVE)
        self.assertEqual(active.tariff, self.plus)

    def test_repeated_webhook_does_not_extend_twice(self):
        payment = self._payment()
        remote = self._remote(payment)
        now = timezone.now()

        with patch('core.services.subscriptions._fetch_yookassa_payment', return_value=remote):
            subscriptions.process_yookassa_payment(payment.yookassa_payment_id, now=now)
            first_expires = UserSubscription.objects.get(user=self.user, status=UserSubscription.Status.ACTIVE).expires_at
            subscriptions.process_yookassa_payment(payment.yookassa_payment_id, now=now)

        second_expires = UserSubscription.objects.get(user=self.user, status=UserSubscription.Status.ACTIVE).expires_at
        self.assertEqual(second_expires, first_expires)

    def test_canceled_webhook_does_not_activate_subscription(self):
        payment = self._payment()

        with patch('core.services.subscriptions._fetch_yookassa_payment', return_value=self._remote(payment, status=SubscriptionPayment.Status.CANCELED)):
            response = self._webhook(payment, event='payment.canceled')

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, SubscriptionPayment.Status.CANCELED)
        self.assertFalse(payment.subscription_activated)
        self.assertFalse(UserSubscription.objects.filter(user=self.user, tariff__is_paid=True).exists())

    def test_amount_currency_or_metadata_mismatch_blocks_activation(self):
        cases = [
            self._remote(self._payment(), value='1.00'),
            self._remote(self._payment(), currency='USD'),
            self._remote(self._payment(), metadata={'payment_uuid': 'bad'}),
        ]

        for remote in cases:
            with self.subTest(remote=remote):
                with patch('core.services.subscriptions._fetch_yookassa_payment', return_value=remote):
                    result = subscriptions.process_yookassa_payment(remote['id'])
                self.assertEqual(result.status, 'error')
                self.assertFalse(UserSubscription.objects.filter(user=self.user, tariff__is_paid=True).exists())

    def test_extension_uses_existing_expires_at(self):
        start = timezone.now()
        active = subscriptions.activate_subscription(
            self.user,
            self.plus,
            billing_period=UserSubscription.BillingPeriod.MONTH,
            starts_at=start,
        )
        payment = self._payment()

        with patch('core.services.subscriptions._fetch_yookassa_payment', return_value=self._remote(payment)):
            subscriptions.process_yookassa_payment(payment.yookassa_payment_id, now=start)

        active.refresh_from_db()
        self.assertEqual(active.expires_at, subscriptions._add_calendar_months(subscriptions._add_calendar_months(start, 1), 1))

    def test_expired_subscription_starts_now(self):
        old_start = timezone.now() - timedelta(days=70)
        now = timezone.now()
        subscriptions.activate_subscription(
            self.user,
            self.plus,
            billing_period=UserSubscription.BillingPeriod.MONTH,
            starts_at=old_start,
        )
        payment = self._payment()

        with patch('core.services.subscriptions._fetch_yookassa_payment', return_value=self._remote(payment)):
            subscriptions.process_yookassa_payment(payment.yookassa_payment_id, now=now)

        active = UserSubscription.objects.get(user=self.user, status=UserSubscription.Status.ACTIVE)
        self.assertEqual(active.tariff, self.plus)
        self.assertEqual(active.starts_at, now)

    def test_plus_to_pro_activates_immediately(self):
        now = timezone.now()
        subscriptions.activate_subscription(self.user, self.plus, billing_period=UserSubscription.BillingPeriod.MONTH, starts_at=now)
        payment = self._payment(tariff=self.pro, period=SubscriptionPayment.Period.YEAR, amount=self.pro.yearly_price)

        with patch('core.services.subscriptions._fetch_yookassa_payment', return_value=self._remote(payment)):
            subscriptions.process_yookassa_payment(payment.yookassa_payment_id, now=now)

        active = UserSubscription.objects.get(user=self.user, status=UserSubscription.Status.ACTIVE)
        self.assertEqual(active.tariff, self.pro)
        self.assertEqual(active.starts_at, now)

    def test_pro_to_plus_is_blocked_until_expiration(self):
        now = timezone.now()
        subscriptions.activate_subscription(self.user, self.pro, billing_period=UserSubscription.BillingPeriod.YEAR, starts_at=now)
        payment = self._payment(tariff=self.plus)

        with patch('core.services.subscriptions._fetch_yookassa_payment', return_value=self._remote(payment)):
            result = subscriptions.process_yookassa_payment(payment.yookassa_payment_id, now=now)

        payment.refresh_from_db()
        active = UserSubscription.objects.get(user=self.user, status=UserSubscription.Status.ACTIVE)
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(active.tariff, self.pro)
        self.assertFalse(payment.subscription_activated)

    def test_user_cannot_view_other_users_payment(self):
        payment = self._payment()

        with self.assertRaises(Http404):
            self._payment_result_response(payment, self.other)

    def test_return_url_does_not_activate_unconfirmed_payment(self):
        payment = self._payment()

        with patch('core.services.subscriptions._fetch_yookassa_payment', return_value=self._remote(payment, status=SubscriptionPayment.Status.PENDING)):
            response = self._payment_result_response(payment, self.user)

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, SubscriptionPayment.Status.PENDING)
        self.assertFalse(payment.subscription_activated)
        self.assertFalse(UserSubscription.objects.filter(user=self.user, tariff__is_paid=True).exists())

    def test_return_url_does_not_activate_succeeded_payment(self):
        payment = self._payment()

        with patch('core.services.subscriptions._fetch_yookassa_payment', return_value=self._remote(payment, status=SubscriptionPayment.Status.SUCCEEDED)):
            response = self._payment_result_response(payment, self.user)

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, SubscriptionPayment.Status.SUCCEEDED)
        self.assertFalse(payment.subscription_activated)
        self.assertFalse(UserSubscription.objects.filter(user=self.user, tariff__is_paid=True).exists())
