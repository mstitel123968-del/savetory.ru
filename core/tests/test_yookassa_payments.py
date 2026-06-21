from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Profile, SubscriptionPayment, SubscriptionPlan
from core.services import subscriptions


YOOKASSA_SETTINGS = {
    'YOOKASSA_ENABLED': True,
    'YOOKASSA_SHOP_ID': 'test-shop',
    'YOOKASSA_SECRET_KEY': 'test-secret',
    'SITE_URL': 'https://www.savetory.ru',
    'YOOKASSA_RETURN_URL': 'https://www.savetory.ru/subscriptions/',
    'YOOKASSA_SEND_RECEIPT': False,
    'YOOKASSA_VAT_CODE': '',
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
            response = self.client.post(
                reverse('core:subscription-checkout'),
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

        invalid_plan = self.client.post(reverse('core:subscription-checkout'), data={'plan': 'free', 'period': 'month'})
        invalid_period = self.client.post(reverse('core:subscription-checkout'), data={'plan': 'plus', 'period': 'week'})

        self.assertEqual(invalid_plan.status_code, 400)
        self.assertEqual(invalid_period.status_code, 400)
        self.assertEqual(SubscriptionPayment.objects.count(), 0)

    @override_settings(**YOOKASSA_SETTINGS)
    def test_successful_creation_saves_payment(self):
        self.client.force_login(self.user)

        with patch('core.services.subscriptions._create_yookassa_payment', return_value=self._sdk_response()) as sdk:
            response = self.client.post(reverse('core:subscription-checkout'), data={'plan': 'pro', 'period': 'year'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['confirmation_url'], 'https://yookassa.example/confirm')
        payment = SubscriptionPayment.objects.get()
        self.assertEqual(payment.tariff.code, SubscriptionPlan.Code.PRO)
        self.assertEqual(payment.period, SubscriptionPayment.Period.YEAR)
        self.assertEqual(payment.amount, Decimal('1990.00'))
        self.assertEqual(payment.yookassa_payment_id, '2f8f-test-payment')
        self.assertEqual(payment.confirmation_url, 'https://yookassa.example/confirm')
        self.assertEqual(sdk.call_count, 1)
        self.assertTrue(payment.idempotence_key)

    @override_settings(**YOOKASSA_SETTINGS)
    def test_double_request_does_not_create_duplicate_payment(self):
        self.client.force_login(self.user)

        with patch('core.services.subscriptions._create_yookassa_payment', return_value=self._sdk_response()) as sdk:
            first = self.client.post(reverse('core:subscription-checkout'), data={'plan': 'plus', 'period': 'month'})
            second = self.client.post(reverse('core:subscription-checkout'), data={'plan': 'plus', 'period': 'month'})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['confirmation_url'], second.json()['confirmation_url'])
        self.assertEqual(SubscriptionPayment.objects.count(), 1)
        self.assertEqual(sdk.call_count, 1)

    @override_settings(**YOOKASSA_SETTINGS)
    def test_sdk_error_is_handled_safely(self):
        self.client.force_login(self.user)

        with patch('core.services.subscriptions._create_yookassa_payment', side_effect=RuntimeError('sdk boom')):
            response = self.client.post(reverse('core:subscription-checkout'), data={'plan': 'plus', 'period': 'month'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('payment', response.json()['errors'])
        payment = SubscriptionPayment.objects.get()
        self.assertEqual(payment.status, SubscriptionPayment.Status.FAILED)
        self.assertNotIn('sdk boom', payment.error_message)

    @override_settings(YOOKASSA_ENABLED=False, YOOKASSA_SHOP_ID='', YOOKASSA_SECRET_KEY='')
    def test_disabled_payments_do_not_break_public_page(self):
        response = self.client.get(reverse('core:subscriptions'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Оплата временно недоступна')

    @override_settings(
        **{
            **YOOKASSA_SETTINGS,
            'YOOKASSA_SEND_RECEIPT': True,
            'YOOKASSA_VAT_CODE': '1',
        }
    )
    def test_receipt_payload_uses_user_email_and_service_item(self):
        self.client.force_login(self.user)
        captured = {}

        def fake_create(payload, idempotence_key):
            captured['payload'] = payload
            return self._sdk_response()

        with patch('core.services.subscriptions._create_yookassa_payment', side_effect=fake_create):
            response = self.client.post(reverse('core:subscription-checkout'), data={'plan': 'plus', 'period': 'month'})

        self.assertEqual(response.status_code, 200)
        receipt = captured['payload']['receipt']
        self.assertEqual(receipt['customer']['email'], 'payer@example.com')
        item = receipt['items'][0]
        self.assertEqual(item['quantity'], '1.00')
        self.assertEqual(item['amount']['value'], '99.00')
        self.assertEqual(item['payment_subject'], 'service')
        self.assertEqual(item['payment_mode'], 'full_payment')
        self.assertEqual(item['vat_code'], 1)
