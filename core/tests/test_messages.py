from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import DirectMessage, DirectMessageReaction
from core.services.messages import MessageError, delete_message, edit_message, get_dialogs, get_message_history, get_unread_summary, mark_messages_read, send_message, set_message_reaction


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

    def test_history_does_not_mark_read_when_disabled(self) -> None:
        message = send_message(self.bob, self.alice, 'hello')

        list(get_message_history(self.alice, self.bob, mark_read=False))

        message.refresh_from_db()
        self.assertFalse(message.is_read)
        self.assertIsNone(message.read_at)

    def test_mark_messages_read_sets_read_at_and_is_idempotent(self) -> None:
        message = send_message(self.bob, self.alice, 'hello')

        marked = mark_messages_read(self.alice, self.bob, [message.pk])

        self.assertEqual(marked, [message.pk])
        message.refresh_from_db()
        self.assertTrue(message.is_read)
        self.assertIsNotNone(message.read_at)

        self.assertEqual(mark_messages_read(self.alice, self.bob, [message.pk]), [])

    def test_mark_messages_read_only_affects_own_incoming(self) -> None:
        incoming = send_message(self.bob, self.alice, 'in')
        outgoing = send_message(self.alice, self.bob, 'out')

        # The sender cannot mark their own outgoing message as read.
        self.assertEqual(mark_messages_read(self.alice, self.bob, [outgoing.pk]), [])
        # A stranger cannot mark a conversation they are not part of.
        self.assertEqual(mark_messages_read(self.carol, self.bob, [incoming.pk]), [])

        incoming.refresh_from_db()
        outgoing.refresh_from_db()
        self.assertFalse(incoming.is_read)
        self.assertFalse(outgoing.is_read)

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

    def test_user_can_replace_and_toggle_message_reaction(self) -> None:
        message = send_message(self.alice, self.bob, 'hello')

        set_message_reaction(self.alice, message, '👍')
        set_message_reaction(self.alice, message, '❤️')

        reaction = DirectMessageReaction.objects.get(message=message, user=self.alice)
        self.assertEqual(reaction.reaction, '❤️')

        set_message_reaction(self.alice, message, '❤️')

        self.assertFalse(DirectMessageReaction.objects.filter(message=message, user=self.alice).exists())

    def test_third_user_cannot_react_to_message(self) -> None:
        message = send_message(self.alice, self.bob, 'hello')

        with self.assertRaises(MessageError):
            set_message_reaction(self.carol, message, '👍')

        self.assertFalse(DirectMessageReaction.objects.exists())

    def test_sender_can_edit_own_message(self) -> None:
        message = send_message(self.alice, self.bob, 'hello')

        updated = edit_message(self.alice, message, 'updated')

        self.assertEqual(updated.text, 'updated')
        self.assertIsNotNone(updated.edited_at)

    def test_non_sender_cannot_edit_or_delete_message(self) -> None:
        message = send_message(self.alice, self.bob, 'hello')

        with self.assertRaises(MessageError):
            edit_message(self.bob, message, 'nope')
        with self.assertRaises(MessageError):
            delete_message(self.bob, message)

    def test_deleted_message_cannot_be_edited_or_reacted_to(self) -> None:
        message = send_message(self.alice, self.bob, 'hello')

        deleted = delete_message(self.alice, message)

        self.assertTrue(deleted.is_deleted)
        self.assertIsNotNone(deleted.deleted_at)
        with self.assertRaises(MessageError):
            edit_message(self.alice, deleted, 'again')
        with self.assertRaises(MessageError):
            set_message_reaction(self.alice, deleted, '👍')


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

    def test_reaction_api_sets_replaces_and_removes_reaction(self) -> None:
        message = send_message(self.bob, self.alice, 'hello')
        self.client.force_login(self.alice)

        response = self.client.post(
            reverse('core:message-reaction-api', kwargs={'message_id': message.pk}),
            data=json.dumps({'reaction': '👍'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DirectMessageReaction.objects.get().reaction, '👍')
        self.assertEqual(response.json()['message']['reactions'][0]['count'], 1)
        self.assertTrue(response.json()['message']['reactions'][0]['selected'])

        response = self.client.post(
            reverse('core:message-reaction-api', kwargs={'message_id': message.pk}),
            data=json.dumps({'reaction': '😂'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DirectMessageReaction.objects.get().reaction, '😂')

        response = self.client.post(
            reverse('core:message-reaction-api', kwargs={'message_id': message.pk}),
            data=json.dumps({'reaction': '😂'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DirectMessageReaction.objects.exists())

    def test_reaction_api_rejects_non_participant(self) -> None:
        carol = get_user_model().objects.create_user('carol', password='pass1234')
        message = send_message(self.bob, self.alice, 'hello')
        self.client.force_login(carol)

        response = self.client.post(
            reverse('core:message-reaction-api', kwargs={'message_id': message.pk}),
            data=json.dumps({'reaction': '👍'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(DirectMessageReaction.objects.exists())

    def test_edit_api_updates_own_message(self) -> None:
        message = send_message(self.alice, self.bob, 'hello')
        self.client.force_login(self.alice)

        response = self.client.patch(
            reverse('core:message-edit-api', kwargs={'message_id': message.pk}),
            data=json.dumps({'text': 'updated'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.text, 'updated')
        self.assertTrue(response.json()['message']['is_edited'])

    def test_edit_api_rejects_empty_text(self) -> None:
        message = send_message(self.alice, self.bob, 'hello')
        self.client.force_login(self.alice)

        response = self.client.patch(
            reverse('core:message-edit-api', kwargs={'message_id': message.pk}),
            data=json.dumps({'text': '   '}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)

    def test_delete_api_soft_deletes_own_message(self) -> None:
        message = send_message(self.alice, self.bob, 'hello')
        set_message_reaction(self.bob, message, '👍')
        self.client.force_login(self.alice)

        response = self.client.post(reverse('core:message-delete-api', kwargs={'message_id': message.pk}))

        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertTrue(message.is_deleted)
        payload = response.json()['message']
        self.assertEqual(payload['text'], 'Сообщение удалено')
        self.assertEqual(payload['reactions'], [])

    def test_delete_api_rejects_non_sender(self) -> None:
        message = send_message(self.alice, self.bob, 'hello')
        self.client.force_login(self.bob)

        response = self.client.post(reverse('core:message-delete-api', kwargs={'message_id': message.pk}))

        self.assertEqual(response.status_code, 403)
        message.refresh_from_db()
        self.assertFalse(message.is_deleted)


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
