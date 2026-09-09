import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.cache import cache
from django.test import TestCase, override_settings
from core.models import DesktopPurchase


@override_settings(SKLAD_PAYMENTS_ENABLED=True, SECURE_SSL_REDIRECT=False, DEBUG=True)
class DesktopLicenseTests(TestCase):
    def setUp(self):
        cache.clear()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        path = Path(self.folder.name) / 'key.pem'
        self.key = Ed25519PrivateKey.generate()
        path.write_bytes(self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.override = override_settings(SKLAD_LICENSE_PRIVATE_KEY_FILE=str(path))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.code = str(uuid.uuid4())

    def post(self, endpoint, **data):
        return self.client.post('/desktop/' + endpoint + '/', json.dumps(data), content_type='application/json')

    @patch('core.desktop_licensing._create_yookassa_payment')
    def test_fixed_price_and_idempotency(self, create):
        create.return_value = {'id': 'payment', 'test': False, 'confirmation': {'confirmation_url': 'https://yookassa.ru/test'}}
        for _ in range(2):
            response = self.post('purchase', purchase_code=self.code, email='buyer@example.com', amount='1.00')
            self.assertEqual(response.status_code, 200)
        self.assertEqual(create.call_count, 1)
        payload = create.call_args.args[0]
        self.assertEqual(payload['amount']['value'], '299.00')
        self.assertNotIn('save_payment_method', payload)
        self.assertEqual(DesktopPurchase.objects.count(), 1)

    def remote(self, **changes):
        result = {'id': 'payment', 'test': False, 'status': 'succeeded', 'paid': True,
                  'amount': {'value': '299.00', 'currency': 'RUB'}, 'metadata': {'desktop_order': self.code}}
        result.update(changes)
        return result

    @patch('core.desktop_licensing._fetch_yookassa_payment')
    def test_verified_payment_issues_signature(self, fetch):
        import base64
        DesktopPurchase.objects.create(id=self.code, email='buyer@example.com', payment_id='payment')
        fetch.return_value = self.remote()
        response = self.post('status', purchase_code=self.code)
        document = response.json()['license']
        self.key.public_key().verify(base64.b64decode(document['signature']), base64.b64decode(document['payload']))
        self.assertTrue(json.loads(base64.b64decode(document['payload']))['perpetual'])

    @patch('core.desktop_licensing._fetch_yookassa_payment')
    def test_unverified_payments_never_activate(self, fetch):
        DesktopPurchase.objects.create(id=self.code, email='buyer@example.com', payment_id='payment')
        for changes in ({'test': True}, {'paid': False}, {'status': 'pending'},
                        {'amount': {'value': '1.00', 'currency': 'RUB'}},
                        {'metadata': {'desktop_order': str(uuid.uuid4())}}, {'id': 'other'}):
            fetch.return_value = self.remote(**changes)
            self.assertNotIn('license', self.post('status', purchase_code=self.code).json())

    @override_settings(SKLAD_PAYMENTS_ENABLED=False)
    @patch('core.desktop_licensing._create_yookassa_payment')
    def test_disabled_does_not_charge(self, create):
        self.assertEqual(self.post('purchase', purchase_code=self.code, email='buyer@example.com').status_code, 503)
        create.assert_not_called()

    def test_unknown_code_cannot_restore(self):
        self.assertEqual(self.post('status', purchase_code=str(uuid.uuid4())).status_code, 404)
