from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import DirectMessage
from core.services.messages import MessageError, get_dialogs, get_message_history, get_unread_summary, send_message


class DirectMessageServiceTests(TestCase):
    def setUp(self) -> None:
        User = get_user_model()
        self.alice = User.objects.create_user('alice', password='pass1234')
        self.bob = User.objects.create_user('bob', password='pass1234')
        self.carol = User.objects.create_user('carol', password='pass1234')

    def test_cannot_send_message_to_self(self) -> None:
        with self.assertRaises(MessageError):
            send_message(self.alice, self.alice, 'hello')

    def test_dialogs_include_latest_message_and_unread_count(self) -> None:
        send_message(self.alice, self.bob, 'one')
        send_message(self.bob, self.alice, 'two')

        dialogs = get_dialogs(self.alice)

        self.assertEqual(len(dialogs), 1)
        self.assertEqual(dialogs[0]['user'], self.bob)
        self.assertEqual(dialogs[0]['latest_message'].text, 'two')
        self.assertEqual(dialogs[0]['unread_count'], 1)

    def test_history_marks_received_messages_as_read(self) -> None:
        message = send_message(self.bob, self.alice, 'hello')

        history = list(get_message_history(self.alice, self.bob))

        self.assertEqual(history, [message])
        message.refresh_from_db()
        self.assertTrue(message.is_read)

    def test_unread_summary_groups_by_sender(self) -> None:
        send_message(self.bob, self.alice, 'hello')
        send_message(self.carol, self.alice, 'second')

        summary = get_unread_summary(self.alice)

        self.assertEqual(summary['total'], 2)
        self.assertEqual({item['user'] for item in summary['senders']}, {self.bob, self.carol})

    def test_third_user_does_not_see_other_conversation(self) -> None:
        send_message(self.alice, self.bob, 'private')

        history = list(get_message_history(self.carol, self.alice))

        self.assertEqual(history, [])


class DirectMessageApiTests(TestCase):
    def setUp(self) -> None:
        User = get_user_model()
        self.alice = User.objects.create_user('alice', password='pass1234')
        self.bob = User.objects.create_user('bob', password='pass1234')

    def test_send_requires_authentication(self) -> None:
        response = self.client.post(
            reverse('core:message-send-api'),
            data=json.dumps({'recipient_id': self.bob.pk, 'text': 'hello'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 302)

    def test_authenticated_user_can_send_message(self) -> None:
        self.client.force_login(self.alice)

        response = self.client.post(
            reverse('core:message-send-api'),
            data=json.dumps({'recipient_id': self.bob.pk, 'text': 'hello'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(DirectMessage.objects.count(), 1)
        self.assertEqual(DirectMessage.objects.get().sender, self.alice)

    def test_api_rejects_self_message(self) -> None:
        self.client.force_login(self.alice)

        response = self.client.post(
            reverse('core:message-send-api'),
            data=json.dumps({'recipient_id': self.alice.pk, 'text': 'hello'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'self_message')

    def test_unread_api_returns_unread_state(self) -> None:
        send_message(self.bob, self.alice, 'hello')
        self.client.force_login(self.alice)

        response = self.client.get(reverse('core:message-unread-api'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['senders'][0]['user']['id'], self.bob.pk)


class DirectMessagePageTests(TestCase):
    def setUp(self) -> None:
        User = get_user_model()
        self.alice = User.objects.create_user('alice', password='pass1234')
        self.bob = User.objects.create_user('bob', password='pass1234')

    def test_messages_page_shows_empty_state(self) -> None:
        self.client.force_login(self.alice)

        response = self.client.get(reverse('core:messages'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Сообщений пока нет')

    def test_messages_page_shows_existing_dialogs(self) -> None:
        send_message(self.bob, self.alice, 'hello from bob')
        self.client.force_login(self.alice)

        response = self.client.get(reverse('core:messages'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bob')
        self.assertContains(response, 'hello from bob')
        self.assertContains(response, reverse('core:message-dialog', kwargs={'user_id': self.bob.pk}))

    def test_dialog_page_opens_history(self) -> None:
        send_message(self.alice, self.bob, 'hello')
        self.client.force_login(self.alice)

        response = self.client.get(reverse('core:message-dialog', kwargs={'user_id': self.bob.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hello')
