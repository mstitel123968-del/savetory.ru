from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import Friendship
from core.services.friendships import (
    FriendshipError,
    accept_request,
    cancel_request,
    get_friends,
    get_incoming_requests,
    get_outgoing_requests,
    get_relationship_status,
    reject_request,
    remove_friend,
    send_request,
)


class FriendshipServiceTests(TestCase):
    def setUp(self) -> None:
        User = get_user_model()
        self.alice = User.objects.create_user('alice', password='pass1234')
        self.bob = User.objects.create_user('bob', password='pass1234')
        self.cara = User.objects.create_user('cara', password='pass1234')

    def test_cannot_add_self(self) -> None:
        with self.assertRaises(FriendshipError) as ctx:
            send_request(self.alice, self.alice)

        self.assertEqual(ctx.exception.code, 'self_friendship')
        self.assertFalse(Friendship.objects.exists())

    def test_reverse_request_does_not_create_duplicate(self) -> None:
        first = send_request(self.alice, self.bob)
        second = send_request(self.bob, self.alice)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Friendship.objects.count(), 1)
        self.assertEqual(second.user_low_id, min(self.alice.id, self.bob.id))
        self.assertEqual(second.user_high_id, max(self.alice.id, self.bob.id))

    def test_only_recipient_can_accept_or_reject(self) -> None:
        send_request(self.alice, self.bob)

        with self.assertRaises(FriendshipError) as accept_ctx:
            accept_request(self.alice, self.bob)
        self.assertEqual(accept_ctx.exception.code, 'not_recipient')

        with self.assertRaises(FriendshipError) as reject_ctx:
            reject_request(self.alice, self.bob)
        self.assertEqual(reject_ctx.exception.code, 'not_recipient')

        relation = accept_request(self.bob, self.alice)
        self.assertEqual(relation.status, Friendship.Status.ACCEPTED)
        self.assertIsNotNone(relation.resolved_at)

    def test_only_sender_can_cancel_pending_request(self) -> None:
        send_request(self.alice, self.bob)

        with self.assertRaises(FriendshipError) as ctx:
            cancel_request(self.bob, self.alice)

        self.assertEqual(ctx.exception.code, 'not_requester')
        self.assertEqual(Friendship.objects.count(), 1)

        cancel_request(self.alice, self.bob)
        self.assertFalse(Friendship.objects.exists())

    def test_accepted_friendship_is_visible_for_both_users(self) -> None:
        send_request(self.alice, self.bob)
        accept_request(self.bob, self.alice)

        self.assertEqual(list(get_friends(self.alice)), [self.bob])
        self.assertEqual(list(get_friends(self.bob)), [self.alice])
        self.assertEqual(get_relationship_status(self.alice, self.bob)['status'], Friendship.Status.ACCEPTED)

    def test_either_friend_can_remove_accepted_friendship(self) -> None:
        send_request(self.alice, self.bob)
        accept_request(self.bob, self.alice)

        remove_friend(self.alice, self.bob)

        self.assertFalse(Friendship.objects.exists())

        send_request(self.alice, self.bob)
        accept_request(self.bob, self.alice)
        remove_friend(self.bob, self.alice)

        self.assertFalse(Friendship.objects.exists())

    def test_outsider_cannot_change_relationship(self) -> None:
        send_request(self.alice, self.bob)

        with self.assertRaises(FriendshipError):
            accept_request(self.cara, self.alice)
        with self.assertRaises(FriendshipError):
            reject_request(self.cara, self.alice)
        with self.assertRaises(FriendshipError):
            cancel_request(self.cara, self.alice)
        with self.assertRaises(FriendshipError):
            remove_friend(self.cara, self.alice)

        relation = Friendship.objects.get()
        self.assertEqual(relation.status, Friendship.Status.PENDING)
        self.assertEqual(relation.requester, self.alice)

    def test_rejected_relationship_is_reused_for_new_request(self) -> None:
        original = send_request(self.alice, self.bob)
        reject_request(self.bob, self.alice)

        refreshed = send_request(self.bob, self.alice)

        self.assertEqual(refreshed.pk, original.pk)
        self.assertEqual(Friendship.objects.count(), 1)
        self.assertEqual(refreshed.status, Friendship.Status.PENDING)
        self.assertEqual(refreshed.requester, self.bob)
        self.assertIsNone(refreshed.resolved_at)

    def test_incoming_and_outgoing_request_lists(self) -> None:
        send_request(self.alice, self.bob)
        send_request(self.cara, self.alice)

        self.assertEqual(list(get_outgoing_requests(self.alice)), [Friendship.objects.get(requester=self.alice)])
        incoming = list(get_incoming_requests(self.alice).order_by('requester__username'))
        self.assertEqual(incoming, [Friendship.objects.get(requester=self.cara)])
