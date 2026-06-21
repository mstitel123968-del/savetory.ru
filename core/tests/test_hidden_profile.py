from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Profile
from core.services.profile_page import build_extended_profile_context


class HiddenProfileTests(TestCase):
    def setUp(self) -> None:
        User = get_user_model()
        self.viewer = User.objects.create_user('viewer', password='pass1234')
        self.hidden = User.objects.create_user('HiddenUser', password='pass1234')
        Profile.objects.create(user=self.viewer, terms_version_accepted=settings.TERMS_VERSION)
        Profile.objects.create(
            user=self.hidden,
            privacy_level='private',
            is_hidden=True,
            terms_version_accepted=settings.TERMS_VERSION,
        )

    def test_hidden_user_is_not_returned_in_people_search(self) -> None:
        self.client.force_login(self.viewer)

        response = self.client.get(reverse('core:community-search-api'), {'q': 'HiddenUser'})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        usernames = {user['username'] for user in payload['users']}
        self.assertNotIn('HiddenUser', usernames)

    def test_hidden_profile_is_not_found_for_other_users(self) -> None:
        context = build_extended_profile_context(self.viewer, 'HiddenUser')

        self.assertFalse(context['found'])

    def test_hidden_profile_is_available_to_owner(self) -> None:
        context = build_extended_profile_context(self.hidden, 'HiddenUser')

        self.assertTrue(context['found'])
        self.assertTrue(context['is_owner'])

    def test_hidden_user_cannot_receive_friendship_request(self) -> None:
        self.client.force_login(self.viewer)

        response = self.client.post(
            reverse('core:community-friendship-api'),
            data=json.dumps({'action': 'send', 'target_id': self.hidden.pk}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)

    def test_migrated_test_user_is_hidden_and_can_login(self) -> None:
        User = get_user_model()
        test_user = User.objects.select_related('profile').get(username='TestUser')

        self.assertTrue(test_user.profile.is_hidden)
        self.assertEqual(test_user.profile.privacy_level, 'private')
        self.assertTrue(self.client.login(username='TestUser', password='Pass1234'))
