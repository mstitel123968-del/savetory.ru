"""Friendship operations for the future community page."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from core.admin_access import configured_admin_login, is_reserved_admin_username
from core.models import Friendship


class FriendshipError(ValueError):
    """Raised when a friendship operation is not allowed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _user_id(user) -> int:
    user_id = getattr(user, 'pk', user)
    if not user_id:
        raise FriendshipError('unsaved_user', 'User must be saved.')
    return int(user_id)


def _assert_distinct(user_a, user_b) -> None:
    if _user_id(user_a) == _user_id(user_b):
        raise FriendshipError('self_friendship', 'A user cannot add themselves as a friend.')
    for user in (user_a, user_b):
        username = getattr(user, 'get_username', lambda: '')()
        if is_reserved_admin_username(username):
            raise FriendshipError('not_found', 'Friendship relation does not exist.')


def _normalize_pair(user_a, user_b):
    _assert_distinct(user_a, user_b)
    return Friendship.normalize_pair(user_a, user_b)


def _pair_filter(user_a, user_b) -> dict:
    user_low, user_high = _normalize_pair(user_a, user_b)
    return {'user_low': user_low, 'user_high': user_high}


def _get_locked_relationship(user_a, user_b) -> Friendship:
    relation = Friendship.objects.select_for_update().filter(**_pair_filter(user_a, user_b)).first()
    if not relation:
        raise FriendshipError('not_found', 'Friendship relation does not exist.')
    return relation


def _ensure_participant(relation: Friendship, user) -> None:
    if _user_id(user) not in {relation.user_low_id, relation.user_high_id}:
        raise FriendshipError('not_participant', 'User is not a participant of this relationship.')


def send_request(sender, recipient) -> Friendship:
    """Create or refresh a pending friendship request."""

    user_low, user_high = _normalize_pair(sender, recipient)
    with transaction.atomic():
        try:
            relation, created = Friendship.objects.select_for_update().get_or_create(
                user_low=user_low,
                user_high=user_high,
                defaults={
                    'requester': sender,
                    'status': Friendship.Status.PENDING,
                    'resolved_at': None,
                },
            )
        except IntegrityError:
            relation = Friendship.objects.select_for_update().get(user_low=user_low, user_high=user_high)
            created = False

        if created:
            return relation

        if relation.status == Friendship.Status.REJECTED:
            relation.requester = sender
            relation.status = Friendship.Status.PENDING
            relation.resolved_at = None
            relation.save(update_fields=['requester', 'status', 'resolved_at', 'updated_at'])
        return relation


def accept_request(actor, other_user) -> Friendship:
    """Accept a pending request. Only the recipient may accept it."""

    with transaction.atomic():
        relation = _get_locked_relationship(actor, other_user)
        _ensure_participant(relation, actor)
        if relation.status != Friendship.Status.PENDING:
            raise FriendshipError('not_pending', 'Only pending requests can be accepted.')
        if relation.requester_id == _user_id(actor):
            raise FriendshipError('not_recipient', 'Only the request recipient can accept it.')
        relation.status = Friendship.Status.ACCEPTED
        relation.resolved_at = timezone.now()
        relation.save(update_fields=['status', 'resolved_at', 'updated_at'])
        return relation


def reject_request(actor, other_user) -> Friendship:
    """Reject a pending request. Only the recipient may reject it."""

    with transaction.atomic():
        relation = _get_locked_relationship(actor, other_user)
        _ensure_participant(relation, actor)
        if relation.status != Friendship.Status.PENDING:
            raise FriendshipError('not_pending', 'Only pending requests can be rejected.')
        if relation.requester_id == _user_id(actor):
            raise FriendshipError('not_recipient', 'Only the request recipient can reject it.')
        relation.status = Friendship.Status.REJECTED
        relation.resolved_at = timezone.now()
        relation.save(update_fields=['status', 'resolved_at', 'updated_at'])
        return relation


def cancel_request(actor, recipient) -> None:
    """Cancel an outgoing pending request. Only the requester may cancel it."""

    with transaction.atomic():
        relation = _get_locked_relationship(actor, recipient)
        _ensure_participant(relation, actor)
        if relation.status != Friendship.Status.PENDING:
            raise FriendshipError('not_pending', 'Only pending requests can be cancelled.')
        if relation.requester_id != _user_id(actor):
            raise FriendshipError('not_requester', 'Only the requester can cancel this request.')
        relation.delete()


def remove_friend(actor, other_user) -> None:
    """Remove an accepted friendship. Either participant may remove it."""

    with transaction.atomic():
        relation = _get_locked_relationship(actor, other_user)
        _ensure_participant(relation, actor)
        if relation.status != Friendship.Status.ACCEPTED:
            raise FriendshipError('not_friends', 'Only accepted friendships can be removed.')
        relation.delete()


def get_relationship_status(user_a, user_b) -> dict:
    """Return normalized relationship state for two users."""

    _assert_distinct(user_a, user_b)
    relation = Friendship.objects.filter(**_pair_filter(user_a, user_b)).first()
    if not relation:
        return {'status': 'none', 'requester_id': None, 'relation': None}
    return {
        'status': relation.status,
        'requester_id': relation.requester_id,
        'relation': relation,
    }


def get_friends(user):
    """Return a queryset of users accepted as friends with the given user."""

    user_id = _user_id(user)
    relations = Friendship.objects.filter(
        Q(user_low_id=user_id) | Q(user_high_id=user_id),
        status=Friendship.Status.ACCEPTED,
    )
    friend_ids = []
    for relation in relations:
        friend_ids.append(relation.user_high_id if relation.user_low_id == user_id else relation.user_low_id)
    qs = get_user_model().objects.filter(id__in=friend_ids).order_by('username', 'id')
    admin_login = configured_admin_login()
    if admin_login:
        qs = qs.exclude(username__iexact=admin_login)
    return qs


def get_incoming_requests(user):
    """Return pending requests sent to the given user."""

    user_id = _user_id(user)
    return Friendship.objects.filter(
        Q(user_low_id=user_id) | Q(user_high_id=user_id),
        status=Friendship.Status.PENDING,
    ).exclude(requester_id=user_id).select_related('user_low', 'user_high', 'requester')


def get_outgoing_requests(user):
    """Return pending requests sent by the given user."""

    return Friendship.objects.filter(
        requester=user,
        status=Friendship.Status.PENDING,
    ).select_related('user_low', 'user_high', 'requester')
