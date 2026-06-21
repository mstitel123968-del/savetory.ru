"""JSON API for the «Аукцион ↔ Ваш архив» integration.

Thin HTTP layer over :mod:`auction.services`. Bidding is intentionally absent
here — it stays on the existing ``market`` endpoints.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.utils.timezone import make_aware
from django.views.decorators.http import require_GET, require_POST

from core.models import ArchiveFile

from . import services
from .constants import AUCTION_FIELD_SCHEMA


def _load_json(request: HttpRequest) -> dict:
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _error(message, *, status: int = 400, field: str | None = None) -> JsonResponse:
    errors = {field: message} if field else {'__all__': message}
    return JsonResponse({'success': False, 'errors': errors}, status=status)


def _errors_response(exc: ValidationError) -> JsonResponse:
    # AuctionError may carry either a dict or a plain message.
    if hasattr(exc, 'message_dict'):
        errors = exc.message_dict
    else:
        errors = {'__all__': exc.messages}
    return JsonResponse({'success': False, 'errors': errors}, status=400)


def _decimal(value, field, errors, *, required=True):
    if value in (None, ''):
        if required:
            errors[field] = 'Поле обязательно.'
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        errors[field] = 'Некорректное числовое значение.'
        return None


def _datetime(value, field, errors):
    if not value:
        errors[field] = 'Укажите дату и время.'
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        errors[field] = 'Некорректный формат даты.'
        return None
    if timezone.is_naive(parsed):
        parsed = make_aware(parsed, timezone.get_current_timezone())
    return parsed


# Auction-only item attributes (not written back to the card structure).
ATTRIBUTE_KEYS = ('condition', 'completeness', 'location', 'handover', 'shipping_cost')


def _collect_attributes(payload: dict) -> dict:
    return {key: str(payload[key]) for key in ATTRIBUTE_KEYS if payload.get(key) not in (None, '')}


def _collect_lot_params(payload: dict) -> tuple[dict, dict]:
    """Extract and validate the shared auction parameters from a payload."""
    errors: dict[str, str] = {}
    params = {
        'category': payload.get('category') or '',
        'start_price': _decimal(payload.get('start_price'), 'start_price', errors),
        'min_bid_step': _decimal(payload.get('min_bid_step'), 'min_bid_step', errors),
        'start_at': _datetime(payload.get('start_at'), 'start_at', errors),
        'end_at': _datetime(payload.get('end_at'), 'end_at', errors),
        'buy_now_price': _decimal(payload.get('buy_now_price'), 'buy_now_price', errors, required=False),
        'reserve_price': _decimal(payload.get('reserve_price'), 'reserve_price', errors, required=False),
        'auto_extend': bool(payload.get('auto_extend')),
        'extend_seconds': int(payload.get('extend_seconds') or 0),
    }
    return params, errors


@login_required
@require_GET
def auction_rubric(request: HttpRequest) -> JsonResponse:
    """Return (creating if needed) the system «Аукцион» rubric for the user."""
    rubric = services.get_or_create_auction_rubric(request.user)
    return JsonResponse({
        'success': True,
        'rubric': {
            'id': rubric.pk,
            'name': rubric.name,
            'slug': rubric.slug,
            'is_system': rubric.is_system,
            'field_schema': rubric.field_schema or AUCTION_FIELD_SCHEMA,
        },
    })


@login_required
@require_POST
def lot_create_from_card(request: HttpRequest) -> JsonResponse:
    """«Выставить на аукцион» an existing archive card (req. 6, 7, 8)."""
    payload = _load_json(request)
    file_id = payload.get('file_id')
    if not file_id:
        return _error('Не указана карточка.', field='file_id')

    card = ArchiveFile.objects.filter(pk=file_id, owner=request.user).first()
    if card is None:
        return _error('Карточка не найдена.', status=404, field='file_id')

    params, errors = _collect_lot_params(payload)
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    mode = payload.get('mode', 'publish')
    if mode not in services.PUBLISH_MODES:
        return _error('Некорректный режим публикации.', field='mode')

    try:
        lot = services.publish_lot_from_card(
            request.user, card,
            title=payload.get('title') or '',
            description=payload.get('description') or '',
            mode=mode,
            attributes=_collect_attributes(payload),
            **params,
        )
    except ValidationError as exc:
        return _errors_response(exc)
    return JsonResponse({'success': True, 'lot': services.serialize_lot_public(lot, request.user),
                         'lot_url': services.lot_detail_path(lot)})


@login_required
@require_POST
def lot_create(request: HttpRequest) -> JsonResponse:
    """Create a card directly in the «Аукцион» rubric and publish it (req. 5)."""
    payload = _load_json(request)
    title = (payload.get('title') or '').strip()
    if not title:
        return _error('Укажите наименование.', field='title')

    params, errors = _collect_lot_params(payload)
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    mode = payload.get('mode', 'publish')
    if mode not in services.PUBLISH_MODES:
        return _error('Некорректный режим публикации.', field='mode')

    data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
    try:
        lot = services.create_card_in_auction(request.user, title=title, data=data, mode=mode, **params)
    except ValidationError as exc:
        return _errors_response(exc)
    return JsonResponse({'success': True, 'lot': services.serialize_lot_public(lot, request.user),
                         'lot_url': services.lot_detail_path(lot)})


@login_required
@require_GET
def card_auction_status(request: HttpRequest, file_id: int) -> JsonResponse:
    """Auction status + actions for a card (req. 9, 10)."""
    card = ArchiveFile.objects.filter(pk=file_id, owner=request.user).first()
    if card is None:
        return _error('Карточка не найдена.', status=404, field='file_id')
    return JsonResponse({'success': True, 'state': services.serialize_card_auction_state(card, request.user)})


@login_required
@require_POST
def lot_relist(request: HttpRequest, lot_id: int) -> JsonResponse:
    """Re-list after cancellation or unsold finish (req. 10)."""
    lot = services.AuctionLot.objects.filter(pk=lot_id, listing__seller=request.user).select_related('listing').first()
    if lot is None:
        return _error('Лот не найден.', status=404, field='lot_id')

    payload = _load_json(request)
    params, errors = _collect_lot_params(payload)
    # category may be inherited from the previous lot
    if not params['category']:
        params.pop('category')
        errors.pop('category', None)
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    try:
        new_lot = services.relist_card(request.user, lot, **params)
    except ValidationError as exc:
        return _errors_response(exc)
    return JsonResponse({'success': True, 'lot': services.serialize_lot_public(new_lot, request.user),
                         'lot_url': services.lot_detail_path(new_lot)})


@login_required
@require_GET
def available_cards(request: HttpRequest) -> JsonResponse:
    """Cards from «Ваш архив» the user may put up for auction (req. 5, 6)."""
    cards = [services.serialize_eligible_card(c) for c in services.eligible_cards_for_user(request.user)]
    return JsonResponse({'success': True, 'cards': cards})


def _get_owned_lot(request, lot_id):
    return (
        services.AuctionLot.objects
        .filter(pk=lot_id, listing__seller=request.user)
        .select_related('listing')
        .first()
    )


@login_required
@require_POST
def lot_bid(request: HttpRequest, lot_id: int) -> JsonResponse:
    """Place a bid on a lot (delegates to market.Bid)."""
    lot = (
        services.AuctionLot.objects.filter(pk=lot_id).select_related('listing').first()
    )
    if lot is None:
        return _error('Лот не найден.', status=404, field='lot_id')
    errors: dict[str, str] = {}
    amount = _decimal(_load_json(request).get('amount'), 'amount', errors)
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)
    try:
        services.place_bid(request.user, lot, amount)
    except ValidationError as exc:
        return _errors_response(exc)
    return JsonResponse({'success': True, 'lot': services.serialize_lot_public(lot, request.user)})


@login_required
@require_POST
def lot_buy_now(request: HttpRequest, lot_id: int) -> JsonResponse:
    """Instant purchase at the buy-now price (req. 3)."""
    lot = services.AuctionLot.objects.filter(pk=lot_id).select_related('listing').first()
    if lot is None:
        return _error('Лот не найден.', status=404, field='lot_id')
    try:
        services.buy_now(request.user, lot)
    except ValidationError as exc:
        return _errors_response(exc)
    return JsonResponse({'success': True, 'lot_url': services.lot_detail_path(lot)})


@login_required
@require_POST
def lot_edit(request: HttpRequest, lot_id: int) -> JsonResponse:
    """Edit description / params before the first bid (req. 11)."""
    lot = _get_owned_lot(request, lot_id)
    if lot is None:
        return _error('Лот не найден.', status=404, field='lot_id')

    payload = _load_json(request)
    errors: dict[str, str] = {}
    fields: dict = {}
    if 'title' in payload:
        fields['title'] = str(payload.get('title') or '')
    if 'description' in payload:
        fields['description'] = str(payload.get('description') or '')
    for name in ('start_price', 'min_bid_step', 'buy_now_price'):
        if name in payload:
            fields[name] = _decimal(payload.get(name), name, errors,
                                    required=(name != 'buy_now_price'))
    for name in ('start_at', 'end_at'):
        if name in payload:
            fields[name] = _datetime(payload.get(name), name, errors)
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    mode = payload.get('mode')
    if mode is not None and mode not in services.PUBLISH_MODES:
        return _error('Некорректный режим публикации.', field='mode')

    try:
        services.edit_lot_before_bids(
            request.user, lot, mode=mode,
            attributes=_collect_attributes(payload), **fields,
        )
    except ValidationError as exc:
        return _errors_response(exc)
    return JsonResponse({'success': True, 'lot': services.serialize_lot_public(lot, request.user),
                         'lot_url': services.lot_detail_path(lot)})
