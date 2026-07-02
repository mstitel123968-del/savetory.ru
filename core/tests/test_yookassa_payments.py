from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Profile, SubscriptionPayment, SubscriptionPlan
from core.services import subscriptions


YOOKASSA_SETTINGS = {
    'YOOKASSA_SHOP_ID': 'test-shop',
    'YOOKASSA_SECRET_KEY': 'test-secret',
    'YOOKASSA_RETURN_URL': 'https://www.savetory.ru/subscriptions/payment/result/',
}


class YooKassaPaymentTests(TestCase):
    def setUp(self):
        subscriptions.seed_default_plans()
        self.user = get_user_model().objects.create_user(
            username='payer',
            email='payer@example.com',
            password='pass1234',
        )
        Profile.objects.create(user=self.user, terms_version_accepted=settings.TERMS_VERSION)

    def _sdk_response(self):
        return {
            'id': '2f8f-test-payment',
            'status': SubscriptionPayment.Status.PENDING,
            'confirmation': {'confirmation_url': 'https://yookassa.example/confirm'},
        }

    def _post_checkout(self, data):
        return self.client.post(
            reverse('core:subscription-checkout'),
            data=data,
            HTTP_ACCEPT='application/json',
        )

    def test_guest_cannot_create_payment(self):
        response = self.client.post(reverse('core:subscription-checkout'), data={'plan': 'plus', 'period': 'month'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(SubscriptionPayment.objects.count(), 0)

    @override_settings(**YOOKASSA_SETTINGS)
    def test_amount_cannot_be_spoofed_by_client(self):
        self.client.force_login(self.user)
        captured = {}

        def fake_create(payload, idempotence_key):
            captured['payload'] = payload
            return self._sdk_response()

        with patch('core.services.subscriptions._create_yookassa_payment', side_effect=fake_create):
            response = self._post_checkout(
                data={'plan': 'plus', 'period': 'month', 'amount': '1.00', 'currency': 'USD'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured['payload']['amount']['value'], '99.00')
        self.assertEqual(captured['payload']['amount']['currency'], 'RUB')
        payment = SubscriptionPayment.objects.get()
        self.assertEqual(payment.amount, Decimal('99.00'))
        self.assertEqual(payment.currency, 'RUB')

    @override_settings(**YOOKASSA_SETTINGS)
    def test_invalid_tariff_and_period_are_rejected(self):
        self.client.force_login(self.user)

        invalid_plan = self._post_checkout(data={'plan': 'free', 'period': 'month'})
        invalid_period = self._post_checkout(data={'plan': 'plus', 'period': 'week'})

        self.assertEqual(invalid_plan.status_code, 400)
        self.assertEqual(invalid_period.status_code, 400)
        self.assertEqual(SubscriptionPayment.objects.count(), 0)

    @override_settings(**YOOKASSA_SETTINGS)
    def test_successful_creation_saves_payment(self):
        self.client.force_login(self.user)

        with patch('core.services.subscriptions._create_yookassa_payment', return_value=self._sdk_response()) as sdk:
            response = self._post_checkout(data={'plan': 'pro', 'period': 'year'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['confirmation_url'], 'https://yookassa.example/confirm')
        payment = SubscriptionPayment.objects.get()
        self.assertEqual(payment.tariff.code, SubscriptionPlan.Code.PRO)
        self.assertEqual(payment.period, SubscriptionPayment.Period.YEAR)
        self.assertEqual(payment.amount, Decimal('1990.00'))
        self.assertEqual(payment.yookassa_payment_id, '2f8f-test-payment')
        self.assertEqual(payment.confirmation_url, 'https://yookassa.example/confirm')
        self.assertEqual(sdk.call_count, 1)
        self.assertEqual(payment.idempotence_key, f'savetory-subscription-{payment.internal_uuid}')
        self.assertEqual(payment.metadata['internal_payment_id'], str(payment.internal_uuid))
        self.assertEqual(payment.metadata['user_id'], str(self.user.pk))
        self.assertEqual(payment.metadata['plan'], SubscriptionPlan.Code.PRO)
        self.assertEqual(payment.metadata['period'], SubscriptionPayment.Period.YEAR)

    @override_settings(**YOOKASSA_SETTINGS)
    def test_double_request_does_not_create_duplicate_payment(self):
        self.client.force_login(self.user)

        with patch('core.services.subscriptions._create_yookassa_payment', return_value=self._sdk_response()) as sdk:
            first = self._post_checkout(data={'plan': 'plus', 'period': 'month'})
            second = self._post_checkout(data={'plan': 'plus', 'period': 'month'})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['confirmation_url'], second.json()['confirmation_url'])
        self.assertEqual(SubscriptionPayment.objects.count(), 1)
        self.assertEqual(sdk.call_count, 1)

    @override_settings(**YOOKASSA_SETTINGS)
    def test_sdk_error_is_handled_safely(self):
        self.client.force_login(self.user)

        with patch('core.services.subscriptions._create_yookassa_payment', side_effect=RuntimeError('sdk boom')):
            response = self._post_checkout(data={'plan': 'plus', 'period': 'month'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('payment', response.json()['errors'])
        payment = SubscriptionPayment.objects.get()
        self.assertEqual(payment.status, SubscriptionPayment.Status.FAILED)
        self.assertNotIn('sdk boom', payment.error_message)

    @override_settings(YOOKASSA_SHOP_ID='', YOOKASSA_SECRET_KEY='', YOOKASSA_RETURN_URL='')
    def test_missing_yookassa_settings_reject_payment_creation(self):
        self.client.force_login(self.user)

        response = self._post_checkout(data={'plan': 'plus', 'period': 'month'})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(SubscriptionPayment.objects.count(), 0)

    @override_settings(**YOOKASSA_SETTINGS)
    def test_checkout_form_returns_safe_redirect(self):
        self.client.force_login(self.user)

        with patch('core.services.subscriptions._create_yookassa_payment', return_value=self._sdk_response()):
            response = self.client.post(reverse('core:subscription-checkout'), data={'plan': 'plus', 'period': 'month'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://yookassa.example/confirm')

    @override_settings(**YOOKASSA_SETTINGS)
    def test_server_prices_match_tariff_table(self):
        self.client.force_login(self.user)
        cases = [
            ('plus', 'month', Decimal('99.00')),
            ('plus', 'year', Decimal('990.00')),
            ('pro', 'month', Decimal('199.00')),
            ('pro', 'year', Decimal('1990.00')),
        ]

        for plan, period, amount in cases:
            SubscriptionPayment.objects.all().delete()
            with self.subTest(plan=plan, period=period):
                with patch('core.services.subscriptions._create_yookassa_payment', return_value=self._sdk_response()):
                    response = self._post_checkout(data={'plan': plan, 'period': period, 'amount': '1.00'})

                self.assertEqual(response.status_code, 200)
                self.assertEqual(SubscriptionPayment.objects.get().amount, amount)
