import base64
import json
import tempfile
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from storage import Storage
from licensing import activate, verify, safe_checkout


class LicenseTests(unittest.TestCase):
    def test_checkout_domains(self):
        self.assertTrue(safe_checkout('https://yoomoney.ru/api-pages/v2/payment-confirm/epl?orderId=1'))
        self.assertTrue(safe_checkout('https://checkout.yookassa.ru/test'))
        for url in ('http://yoomoney.ru/pay', 'https://yoomoney.ru.attacker.test/',
                    'https://attacker.test/yookassa.ru', 'file:///test', 'https://a@yoomoney.ru'):
            self.assertFalse(safe_checkout(url))

    def test_limit_and_perpetual_activation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = Ed25519PrivateKey.generate()
            (root / 'license-public.pem').write_bytes(key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
            store = Storage(root, root, root / 'data')
            for n in range(10):
                store.add_card('coins', {'title': str(n)})
            with self.assertRaises(ValueError):
                store.add_card('coins', {'title': '11'}, ['missing-photo.jpg'])
            self.assertEqual(len(store.data['cards']), 10)
            store.update_card(store.data['cards'][0]['id'], 'coins', {'title': 'Editable'})
            payload = json.dumps({'product': 'sklad-desktop', 'version': 1, 'perpetual': True, 'license_id': 'test'}).encode()
            document = {'payload': base64.b64encode(payload).decode(), 'signature': base64.b64encode(key.sign(payload)).decode()}
            activate(document, store.data_dir, root)
            store.add_card('coins', {'title': '11'})
            self.assertTrue(Storage(root, root, root / 'data').is_licensed())
            self.assertEqual(len(store.data['cards']), 11)
            document['payload'] = base64.b64encode(payload + b' ').decode()
            self.assertFalse(verify(document, root / 'license-public.pem'))

    def test_existing_large_collection_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = Storage(root, root, root / 'data')
            store.data['cards'] = [{'id': str(n), 'rubric_id': 'coins', 'values': {'title': str(n)}, 'images': []} for n in range(20)]
            store.save()
            loaded = Storage(root, root, root / 'data')
            self.assertEqual(len(loaded.data['cards']), 20)
            self.assertFalse(loaded.can_add_card())


if __name__ == '__main__':
    unittest.main()
