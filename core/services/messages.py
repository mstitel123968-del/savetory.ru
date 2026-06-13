"""Private messaging operations."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import DirectMessage, DirectMessageReaction


ALLOWED_MESSAGE_REACTIONS = tuple(choice.value for choice in DirectMessageReaction.Reaction)


class MessageError(ValueError):
    """Raised when a private message operation is not allowed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _user_id(user) -> int:
    user_id = getattr(user, 'pk', user)
    if not user_id:
        raise MessageError('unsaved_user', 'User must be saved.')
    return int(user_id)


def _assert_distinct(sender, recipient) -> None:
    if _user_id(sender) == _user_id(recipient):
        raise MessageError('self_message', 'A user cannot send a message to themselves.')


def _conversation_filter(user, other_user) -> Q:
    _assert_distinct(user, other_user)
    return (
        Q(sender=user, recipient=other_user)
        | Q(sender=other_user, recipient=user)
    )


def send_message(sender, recipient, text: str) -> DirectMessage:
    """Create a new private message."""

    _assert_distinct(sender, recipient)
    body = str(text or '').strip()
    if not body:
        raise MessageError('empty_message', 'Message text cannot be empty.')
    with transaction.atomic():
        message = DirectMessage(sender=sender, recipient=recipient, text=body)
        message.full_clean()
        message.save()
        return message


def edit_message(actor, message: DirectMessage, text: str) -> DirectMessage:
    """Edit an own non-deleted private message."""

    if _user_id(actor) != message.sender_id:
        raise MessageError('not_sender', 'Only the message sender can edit it.')
    if message.is_deleted:
        raise MessageError('message_deleted', 'Deleted messages cannot be edited.')
    body = str(text or '').strip()
    if not body:
        raise MessageError('empty_message', 'Message text cannot be empty.')
    with transaction.atomic():
        locked_message = DirectMessage.objects.select_for_update().get(pk=message.pk)
        if _user_id(actor) != locked_message.sender_id:
            raise MessageError('not_sender', 'Only the message sender can edit it.')
        if locked_message.is_deleted:
            raise MessageError('message_deleted', 'Deleted messages cannot be edited.')
        locked_message.text = body
        locked_message.edited_at = timezone.now()
        locked_message.full_clean()
        locked_message.save(update_fields=['text', 'edited_at'])
        return locked_message


def delete_message(actor, message: DirectMessage) -> DirectMessage:
    """Soft-delete an own private message."""

    if _user_id(actor) != message.sender_id:
        raise MessageError('not_sender', 'Only the message sender can delete it.')
    if message.is_deleted:
        return message
    with transaction.atomic():
        locked_message = DirectMessage.objects.select_for_update().get(pk=message.pk)
        if _user_id(actor) != locked_message.sender_id:
            raise MessageError('not_sender', 'Only the message sender can delete it.')
        if locked_message.is_deleted:
            return locked_message
        locked_message.is_deleted = True
        locked_message.deleted_at = timezone.now()
        locked_message.save(update_fields=['is_deleted', 'deleted_at'])
        return locked_message


def get_message_history(user, other_user, *, mark_read: bool = True):
    """Return messages between two participants, optionally marking received messages as read."""

    queryset = DirectMessage.objects.filter(_conversation_filter(user, other_user)).select_related('sender', 'recipient').prefetch_related('reactions').order_by('sent_at', 'id')
    if mark_read:
        DirectMessage.objects.filter(sender=other_user, recipient=user, is_read=False).update(is_read=True)
    return queryset


def get_dialogs(user):
    """Return dialog summaries for the current user."""

    user_id = _user_id(user)
    messages = DirectMessage.objects.filter(Q(sender_id=user_id) | Q(recipient_id=user_id)).select_related('sender', 'recipient').order_by('-sent_at', '-id')
    dialog_map: dict[int, dict] = {}
    for message in messages:
        other_id = message.recipient_id if message.sender_id == user_id else message.sender_id
        if other_id not in dialog_map:
            dialog_map[other_id] = {
                'user_id': other_id,
                'latest_message': message,
                'latest_at': message.sent_at,
                'unread_count': 0,
                'message_count': 0,
            }
        dialog_map[other_id]['message_count'] += 1
        if message.recipient_id == user_id and not message.is_read:
            dialog_map[other_id]['unread_count'] += 1

    users = {
        participant.pk: participant
        for participant in get_user_model().objects.filter(pk__in=dialog_map.keys()).select_related('profile')
    }
    dialogs = []
    for other_id, dialog in dialog_map.items():
        other = users.get(other_id)
        if other:
            dialogs.append({**dialog, 'user': other})
    return sorted(dialogs, key=lambda item: (item['latest_at'], item['user_id']), reverse=True)


def get_unread_summary(user) -> dict:
    """Return unread message counters grouped by sender for the current user."""

    user_id = _user_id(user)
    unread = DirectMessage.objects.filter(recipient_id=user_id, is_read=False).select_related('sender').order_by('-sent_at', '-id')
    senders: dict[int, dict] = {}
    latest_at = None
    total = 0
    for message in unread:
        total += 1
        if latest_at is None or message.sent_at > latest_at:
            latest_at = message.sent_at
        sender_data = senders.setdefault(message.sender_id, {
            'user': message.sender,
            'count': 0,
            'latest_at': message.sent_at,
        })
        sender_data['count'] += 1
        if message.sent_at > sender_data['latest_at']:
            sender_data['latest_at'] = message.sent_at
    return {
        'total': total,
        'latest_at': latest_at,
        'senders': list(senders.values()),
    }


def ensure_conversation_participant(user, message: DirectMessage) -> None:
    """Ensure a user can access a stored message."""

    user_id = _user_id(user)
    if user_id not in {message.sender_id, message.recipient_id}:
        raise MessageError('not_participant', 'User is not a participant of this conversation.')


def set_message_reaction(user, message: DirectMessage, reaction: str | None) -> DirectMessage:
    """Set, replace, or remove the current user's reaction for a message."""

    ensure_conversation_participant(user, message)
    if getattr(message, 'is_deleted', False) or getattr(message, 'deleted_at', None):
        raise MessageError('message_deleted', 'Deleted messages cannot be reacted to.')

    value = str(reaction or '').strip()
    if value and value not in ALLOWED_MESSAGE_REACTIONS:
        raise MessageError('invalid_reaction', 'Unsupported message reaction.')

    with transaction.atomic():
        locked_message = DirectMessage.objects.select_for_update().get(pk=message.pk)
        ensure_conversation_participant(user, locked_message)
        current = DirectMessageReaction.objects.select_for_update().filter(message=locked_message, user=user).first()
        if not value or (current and current.reaction == value):
            if current:
                current.delete()
            return locked_message
        if current:
            current.reaction = value
            current.full_clean()
            current.save(update_fields=['reaction', 'updated_at'])
        else:
            reaction_obj = DirectMessageReaction(message=locked_message, user=user, reaction=value)
            reaction_obj.full_clean()
            reaction_obj.save()
        return locked_message
