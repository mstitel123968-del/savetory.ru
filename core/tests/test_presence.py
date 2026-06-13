from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.middleware import LastSeenMiddleware
from core.models import Profile
from core.views import _community_presence_payload


class PresencePayloadTests(TestCase):
    def test_missing_activity_shows_fallback_label(self) -> None:
        payload = _community_presence_payload(Profile(last_seen_at=None))

        self.assertFalse(payload['is_online'])
        self.assertEqual(payload['label'], 'Активность пока неизвестна')

    def test_recent_activity_is_online(self) -> None:
        now = timezone.now()
        profile = Profile(last_seen_at=now - timedelta(minutes=4, seconds=30))

        with patch('core.views.timezone.now', return_value=now):
            payload = _community_presence_payload(profile)

        self.assertTrue(payload['is_online'])
        self.assertEqual(payload['label'], 'Онлайн')

    def test_activity_older_than_online_window_shows_last_seen(self) -> None:
        now = timezone.now()
        profile = Profile(last_seen_at=now - timedelta(minutes=6))

        with patch('core.views.timezone.now', return_value=now):
            payload = _community_presence_payload(profile)

        self.assertFalse(payload['is_online'])
        self.assertIn('Заходил сегодня в', payload['label'])


class LastSeenMiddlewareTests(TestCase):
    def test_frequent_requests_do_not_update_more_than_once_per_minute(self) -> None:
        User = get_user_model()
        user = User.objects.create_user('alice', password='pass1234')
        session = SessionStore()
        factory = RequestFactory()
        middleware = LastSeenMiddleware(lambda request: HttpResponse('ok'))
        first_seen = timezone.now()

        first_request = factory.get('/community/')
        first_request.user = user
        first_request.session = session
        with patch('core.middleware.timezone.now', return_value=first_seen):
            middleware(first_request)

        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.last_seen_at, first_seen)

        second_request = factory.get('/community/')
        second_request.user = user
        second_request.session = session
        with patch('core.middleware.timezone.now', return_value=first_seen + timedelta(seconds=30)):
            middleware(second_request)

        profile.refresh_from_db()
        self.assertEqual(profile.last_seen_at, first_seen)

        third_request = factory.get('/community/')
        third_request.user = user
        third_request.session = session
        later_seen = first_seen + timedelta(seconds=61)
        with patch('core.middleware.timezone.now', return_value=later_seen):
            middleware(third_request)

        profile.refresh_from_db()
        self.assertEqual(profile.last_seen_at, later_seen)
