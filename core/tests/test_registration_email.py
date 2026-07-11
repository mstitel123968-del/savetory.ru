from datetime import timedelta
import re
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import PendingRegistration, Profile


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='СКлад <no-reply@savetory.ru>',
)
class EmailRegistrationTests(TestCase):
    password = 'StrongPass!123'

    def payload(self, **overrides):
        data = {
            'username': 'new_user',
            'email': 'USER@Example.com',
            'password1': self.password,
            'password2': self.password,
            'terms_accepted': '1',
            'terms_version': settings.TERMS_VERSION,
        }
        data.update(overrides)
        return data

    def start(self, **overrides):
        return self.client.post(reverse('core:register'), self.payload(**overrides))

    def sent_code(self, index=-1):
        match = re.search(r'(?<!\d)(\d{6})(?!\d)', mail.outbox[index].body)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_terms_are_required_and_version_must_be_current(self):
        response = self.start(terms_accepted='0')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(mail.outbox)
        response = self.start(terms_version='old')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PendingRegistration.objects.exists())

    def test_invalid_email_duplicate_identity_and_bad_password_are_rejected(self):
        User = get_user_model()
        User.objects.create_user('occupied', email='occupied@example.com', password=self.password)
        self.assertEqual(self.start(email='bad').status_code, 400)
        self.assertEqual(self.start(username='occupied').status_code, 400)
        self.assertEqual(self.start(email='occupied@example.com').status_code, 400)
        self.assertEqual(self.start(password1='short', password2='different').status_code, 400)

    def test_start_sends_six_digit_code_without_creating_user_or_storing_secrets(self):
        response = self.start()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='new_user').exists())
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['user@example.com'])
        self.assertEqual(message.from_email, 'СКлад <no-reply@savetory.ru>')
        self.assertTrue(any(mimetype == 'text/html' for _content, mimetype in message.alternatives))
        code = self.sent_code()
        self.assertRegex(code, r'^\d{6}$')
        pending = PendingRegistration.objects.get()
        self.assertNotEqual(pending.code_hash, code)
        self.assertNotIn(self.password, pending.password_hash)
        self.assertTrue(check_password(code, pending.code_hash))
        self.assertTrue(check_password(self.password, pending.password_hash))

    def test_wrong_code_locks_after_five_attempts(self):
        self.start()
        for _ in range(4):
            response = self.client.post(reverse('core:register-verify'), {'code': '000000'})
            self.assertEqual(response.status_code, 400)
        response = self.client.post(reverse('core:register-verify'), {'code': '000000'})
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.json()['blocked'])
        self.assertFalse(get_user_model().objects.filter(username='new_user').exists())

    def test_expired_code_is_rejected(self):
        self.start()
        PendingRegistration.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post(reverse('core:register-verify'), {'code': self.sent_code()})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()['expired'])

    def test_resend_is_throttled_and_replaces_code(self):
        self.start()
        old_code = self.sent_code()
        response = self.client.post(reverse('core:register-resend'))
        self.assertEqual(response.status_code, 429)
        PendingRegistration.objects.update(resend_available_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post(reverse('core:register-resend'))
        self.assertEqual(response.status_code, 200)
        new_code = self.sent_code()
        self.assertNotEqual(old_code, new_code)
        self.assertFalse(check_password(old_code, PendingRegistration.objects.get().code_hash))
        self.assertTrue(check_password(new_code, PendingRegistration.objects.get().code_hash))

    def test_fifth_total_send_exhausts_resend_limit(self):
        self.start()
        for _ in range(4):
            PendingRegistration.objects.update(resend_available_at=timezone.now() - timedelta(seconds=1))
            self.assertEqual(self.client.post(reverse('core:register-resend')).status_code, 200)
        PendingRegistration.objects.update(resend_available_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post(reverse('core:register-resend'))
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.json()['blocked'])
        self.assertFalse(PendingRegistration.objects.exists())

    def test_correct_code_creates_profile_accepts_terms_and_logs_in_once(self):
        self.start()
        code = self.sent_code()
        response = self.client.post(reverse('core:register-verify'), {'code': code})
        self.assertEqual(response.status_code, 200)
        user = get_user_model().objects.get(username='new_user')
        self.assertEqual(user.email, 'user@example.com')
        self.assertTrue(user.check_password(self.password))
        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.terms_version_accepted, settings.TERMS_VERSION)
        self.assertIn('_auth_user_id', self.client.session)
        replay = self.client.post(reverse('core:register-verify'), {'code': code})
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(get_user_model().objects.filter(username='new_user').count(), 1)

    @patch('core.views._send_registration_code', side_effect=RuntimeError('smtp unavailable'))
    def test_email_failure_does_not_create_user_and_invalidates_pending(self, _send):
        response = self.start()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(get_user_model().objects.filter(username='new_user').exists())
        self.assertFalse(PendingRegistration.objects.exists())
