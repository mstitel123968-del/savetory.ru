"""Replaces the Java Spring MVC controllers with Django view functions."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from datetime import timedelta
from urllib.parse import unquote

from PIL import Image, UnidentifiedImageError

from django.db import transaction
from django.db.models import Q

from django.conf import settings as django_settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.crypto import get_random_string
from django.urls import reverse
from django.utils.text import slugify
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core import messages
from core import exporters
from core.admin_access import configured_admin_login, is_reserved_admin_username
from core.utils import moderation
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
from core.services.messages import (
    ALLOWED_MESSAGE_REACTIONS,
    MessageError,
    delete_message,
    edit_message,
    get_dialogs,
    get_message_history,
    get_unread_summary,
    mark_messages_read,
    send_message,
    set_message_reaction,
)
from core.services.profile_page import (
    build_extended_profile_context,
    validate_profile_background,
)
from core.services import subscriptions
from .forms import ArchiveFileForm, LoginForm, RegistrationForm, RubricForm
from .models import ArchiveFile, ArchiveState, DirectMessage, Friendship, NewsArticle, Profile, Review, Rubric, SubscriptionPayment

logger = logging.getLogger("core.moderation")
payment_logger = logging.getLogger("core.payments")

FILE_STATUS_LABELS = {
    'keep': 'Храню',
    'sell': 'Готов продать',
    'exchange': 'Готов обменять',
    'search': 'Ищу такой же',
    'sold': 'Продано',
}


def _normalize_file_status(value) -> str:
    status = str(value or '').strip().lower()
    return status if status in FILE_STATUS_LABELS else 'keep'


def _normalize_public_slug(value: str, fallback: str = '') -> str:
    source = str(value or fallback or '').strip()
    normalized = slugify(source, allow_unicode=True)
    if not normalized:
        normalized = re.sub(r'[^0-9A-Za-zА-Яа-яЁё_-]+', '-', source).strip('-_').lower()
    return (normalized or 'collection')[:255]


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return False


PROFILE_COVER_MAX_SIZE = 10 * 1024 * 1024
PROFILE_COVER_CONTENT_TYPES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
}
PROFILE_COVER_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}


def _is_user_profile_cover_path(path: str) -> bool:
    try:
        normalized = validate_profile_background(path)
    except ValueError:
        return False
    return bool(normalized)


def _delete_profile_cover(path: str) -> None:
    if _is_user_profile_cover_path(path) and default_storage.exists(path):
        default_storage.delete(path)


def _profile_cover_payload(path: str) -> dict | None:
    try:
        normalized = validate_profile_background(path)
    except ValueError:
        return None
    if not normalized:
        return None
    return {
        'id': normalized,
        'path': normalized,
        'url': default_storage.url(normalized),
    }


def _save_profile_cover_upload(user: User, upload) -> str:
    if not upload:
        raise ValueError('Выберите изображение для обложки.')
    if upload.size and upload.size > PROFILE_COVER_MAX_SIZE:
        raise ValueError('Файл слишком большой. Максимальный размер обложки — 10 МБ.')

    content_type = str(getattr(upload, 'content_type', '') or '').lower()
    source_ext = Path(str(upload.name or '')).suffix.lower()
    if source_ext not in PROFILE_COVER_EXTENSIONS or content_type not in PROFILE_COVER_CONTENT_TYPES:
        raise ValueError('Поддерживаются только JPG, PNG и WEBP.')

    try:
        with Image.open(upload) as image:
            image.verify()
            detected_format = str(image.format or '').upper()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError('Файл не похож на корректное изображение.') from exc
    finally:
        try:
            upload.seek(0)
        except (AttributeError, OSError):
            pass

    if detected_format not in {'JPEG', 'PNG', 'WEBP'}:
        raise ValueError('Поддерживаются только JPG, PNG и WEBP.')

    ext = PROFILE_COVER_CONTENT_TYPES[content_type]
    filename = f"cover_{timezone.now():%Y%m%d%H%M%S}_{get_random_string(8)}{ext}"
    return default_storage.save(f"profile_covers/user_{user.pk}/{filename}", upload)


def _dedupe_public_slug(raw_slug: str, used_slugs: set[str], fallback: str = '') -> str:
    base = _normalize_public_slug(raw_slug, fallback)
    candidate = base
    index = 2
    while candidate in used_slugs:
        suffix = f'-{index}'
        candidate = f'{base[:255 - len(suffix)]}{suffix}'
        index += 1
    used_slugs.add(candidate)
    return candidate


def _normalize_public_rubric_state(state_data: dict) -> bool:
    rubrics = state_data.get('rubrics')
    if not isinstance(rubrics, list):
        return False

    changed = False
    used_slugs: set[str] = set()
    for rubric in rubrics:
        if not isinstance(rubric, dict):
            continue
        current_slug = str(rubric.get('publicSlug') or rubric.get('slug') or '').strip()
        fallback = str(rubric.get('name') or rubric.get('id') or 'collection')
        normalized_slug = _dedupe_public_slug(current_slug, used_slugs, fallback)
        if rubric.get('publicSlug') != normalized_slug:
            rubric['publicSlug'] = normalized_slug
            changed = True
        if 'publicEnabled' not in rubric:
            rubric['publicEnabled'] = False
            changed = True
        else:
            normalized_enabled = _coerce_bool(rubric.get('publicEnabled'))
            if rubric.get('publicEnabled') is not normalized_enabled:
                rubric['publicEnabled'] = normalized_enabled
                changed = True
    return changed


def _public_image_items(value) -> dict:
    if not value:
        return []
    source = []
    frame_width = value.get('frameWidth') if isinstance(value, dict) else None
    frame_height = value.get('frameHeight') if isinstance(value, dict) else None

    if isinstance(value, dict):
        if isinstance(value.get('items'), list):
            source = value.get('items') or []
        elif value.get('src'):
            source = [value]
    elif isinstance(value, list):
        source = value
    elif isinstance(value, str):
        source = [{'src': value}]

    items = []
    for item in source:
        if isinstance(item, str):
            src = item
            item_id = src
        elif isinstance(item, dict):
            src = str(item.get('src') or '')
            item_id = str(item.get('id') or src)
        else:
            continue
        if src:
            items.append({'id': item_id, 'src': src})
    return {
        'items': items,
        'frameWidth': frame_width if isinstance(frame_width, (int, float)) and frame_width > 0 else None,
        'frameHeight': frame_height if isinstance(frame_height, (int, float)) and frame_height > 0 else None,
    }


def _prepare_public_collection(rubric: dict) -> dict:
    fields = [field for field in rubric.get('fields', []) if isinstance(field, dict) and field.get('id')]
    field_map = {str(field.get('id')): field for field in fields}
    files = rubric.get('files') if isinstance(rubric.get('files'), list) else []
    photo_field = next((field for field in fields if field.get('type') == 'image'), None)
    title_field = field_map.get('title')

    cards = []
    for file_item in files:
        if not isinstance(file_item, dict):
            continue
        values = file_item.get('values') if isinstance(file_item.get('values'), dict) else {}
        title = ''
        if title_field:
            raw_title = values.get(str(title_field.get('id')))
            if raw_title is not None:
                title = str(raw_title).strip()
        if not title:
            title = str(rubric.get('name') or 'Карточка')

        status = _normalize_file_status(file_item.get('status'))
        image_value = _public_image_items(values.get(str(photo_field.get('id'))) if photo_field else None)
        details = []
        for field in fields:
            field_id = str(field.get('id') or '')
            if not field_id or field.get('type') == 'image' or field_id == 'title':
                continue
            raw_value = values.get(field_id)
            value = str(raw_value).strip() if raw_value is not None else ''
            details.append({
                'id': field_id,
                'label': str(field.get('label') or 'Поле'),
                'value': value,
                'type': str(field.get('type') or 'text'),
            })

        cards.append({
            'id': str(file_item.get('id') or ''),
            'title': title,
            'status': status,
            'statusLabel': FILE_STATUS_LABELS[status],
            'images': image_value['items'],
            'imageFrame': {
                'width': image_value['frameWidth'],
                'height': image_value['frameHeight'],
            },
            'details': details,
        })

    return {
        'name': str(rubric.get('name') or 'Коллекция'),
        'slug': str(rubric.get('publicSlug') or ''),
        'cards': cards,
        'fields': fields,
    }


def _seo_context(
    request: HttpRequest,
    *,
    title: str,
    description: str,
    indexable: bool,
    canonical_path: str | None = None,
) -> dict[str, str]:
    path = canonical_path or request.path
    return {
        "seo_title": title,
        "seo_description": description,
        "seo_robots": "index,follow" if indexable else "noindex,nofollow",
        "canonical_url": request.build_absolute_uri(path),
    }


@ensure_csrf_cookie
def landing(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect('core:archive')
    return render(
        request,
        'index.html',
        _seo_context(
            request,
            title='СКлад - хранение информации о вещах и подготовка к продаже',
            description='СКлад помогает хранить фото, характеристики, заметки и историю вещей в одном месте, а также готовить их к продаже.',
            indexable=True,
            canonical_path=reverse('core:landing'),
        ),
    )


@ensure_csrf_cookie
@never_cache
def archive(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'archive.html',
        _seo_context(
            request,
            title='Ваш архив - СКлад',
            description='Личный архив пользователя для хранения вещей, заметок и файлов.',
            indexable=False,
            canonical_path=reverse('core:archive'),
        ),
    )


@ensure_csrf_cookie
@never_cache
def public_collection(request: HttpRequest, username: str, rubric_slug: str) -> HttpResponse:
    if is_reserved_admin_username(username):
        return render(request, 'public_collection_unavailable.html', status=404)
    user = User.objects.filter(username__iexact=username).first()
    if not user:
        return render(request, 'public_collection_unavailable.html', status=404)
    profile = getattr(user, 'profile', None)
    can_view_hidden = request.user.is_authenticated and (request.user.pk == user.pk or request.user.is_superuser)
    if profile and profile.is_hidden and not can_view_hidden:
        return render(request, 'public_collection_unavailable.html', status=404)

    state = ArchiveState.objects.filter(user=user).first()
    state_data = state.data if state and isinstance(state.data, dict) else {'rubrics': []}
    rubrics = state_data.get('rubrics') if isinstance(state_data.get('rubrics'), list) else []
    requested_slug = _normalize_public_slug(unquote(rubric_slug))

    rubric = None
    for candidate in rubrics:
        if not isinstance(candidate, dict):
            continue
        candidate_slug = _normalize_public_slug(str(candidate.get('publicSlug') or candidate.get('slug') or ''), str(candidate.get('name') or ''))
        if candidate_slug == requested_slug:
            rubric = candidate
            break

    if not rubric or not _coerce_bool(rubric.get('publicEnabled')):
        return render(request, 'public_collection_unavailable.html', status=404)

    collection = _prepare_public_collection(rubric)
    return render(
        request,
        'public_collection.html',
        {
            'collection': collection,
            **_seo_context(
                request,
                title=f"{collection['name']} - СКЛад",
                description=f"Публичная коллекция {collection['name']}.",
                indexable=True,
            ),
        },
    )


@login_required
@ensure_csrf_cookie
def profile(request: HttpRequest) -> HttpResponse:
    profile_page = build_extended_profile_context(request.user, request.user.get_username())
    profile_data = profile_page['profile']
    return render(
        request,
        'community_user_profile.html',
        {
            'profile_page': profile_page,
            'profile_nav_section': 'profile',
            'profile_canonical_path': reverse('core:profile'),
            **_seo_context(
                request,
                title=f"{profile_data['display_name']} - профиль - СКлад",
                description='Личный профиль пользователя сервиса СКлад.',
                indexable=False,
                canonical_path=reverse('core:profile'),
            ),
        },
    )


@ensure_csrf_cookie
def settings(request: HttpRequest) -> HttpResponse:
    subscription_context = {}
    if request.user.is_authenticated:
        limits = subscriptions.subscription_limits(request.user)
        subscription_context = {
            'subscription': limits['subscription'],
            'subscription_plan': limits['plan'],
            'subscription_limits': limits,
            'available_plans': subscriptions.available_plan_cards(),
            'payment_enabled': True,
            'settings_can_customize_colors': limits['plan'].code == subscriptions.SubscriptionPlan.Code.PRO,
        }
    return render(
        request,
        'settings.html',
        {
            'settings_can_customize_colors': False,
            **subscription_context,
            **_seo_context(
            request,
            title='Настройки - СКлад',
            description='Персональные настройки интерфейса и приватности пользователя.',
            indexable=False,
            canonical_path=reverse('core:settings'),
            ),
        },
    )


def market_closed(request: HttpRequest, path: str = '') -> HttpResponse:
    return render(
        request,
        'market_closed.html',
        _seo_context(
            request,
            title='Market temporarily closed - SKLad',
            description='Market access is temporarily closed.',
            indexable=False,
        ),
        status=503,
    )


@login_required
@ensure_csrf_cookie
def community(request: HttpRequest) -> HttpResponse:
    tab = str(request.GET.get('tab') or 'search').strip().lower()
    if tab not in {'search', 'friends', 'requests'}:
        tab = 'search'
    requests_view = str(request.GET.get('requests') or 'incoming').strip().lower()
    if requests_view not in {'incoming', 'outgoing'}:
        requests_view = 'incoming'
    return render(
        request,
        'community.html',
        {
            'initial_tab': tab,
            'initial_requests_view': requests_view,
            **_seo_context(
                request,
                title='Люди - СКлад',
                description='Поиск пользователей, друзья и заявки в разделе Люди СКлада.',
                indexable=False,
                canonical_path=reverse('core:community'),
            ),
        },
    )


def _dialog_preview_text(message, viewer: User) -> str:
    """Dialog-list preview that shows who sent the last message.

    Outgoing messages are prefixed with «Вы: »; incoming ones show the plain
    text. A message with no text (an attachment) shows a generic label instead.
    Deleted messages keep their neutral system note without a prefix.
    """
    if message.is_deleted:
        return 'Сообщение удалено'
    body = (message.text or '').strip()
    if not body:
        # Attachment without text: show a fitting label by kind.
        body = 'Фото' if message.attachment_kind == 'image' else 'Файл'
    if message.sender_id == viewer.pk:
        return f'Вы: {body}'
    return body


@login_required
@ensure_csrf_cookie
def messages_page(request: HttpRequest) -> HttpResponse:
    dialogs = get_dialogs(request.user)
    dialog_rows = []
    for dialog in dialogs:
        dialog_rows.append({
            'user': dialog['user'],
            'display_name': _community_display_name(dialog['user'], getattr(dialog['user'], 'profile', None)),
            'latest_message': dialog['latest_message'],
            'latest_text': _dialog_preview_text(dialog['latest_message'], request.user),
            'latest_at': timezone.localtime(dialog['latest_at']),
            'unread_count': dialog['unread_count'],
            'url': reverse('core:message-dialog', kwargs={'user_id': dialog['user'].pk}),
        })
    return render(
        request,
        'messages.html',
        {
            'dialogs': dialog_rows,
            **_seo_context(
                request,
                title='Сообщения - СКлад',
                description='Личные сообщения пользователей СКлада.',
                indexable=False,
                canonical_path=reverse('core:messages'),
            ),
        },
    )


@login_required
@ensure_csrf_cookie
def message_dialog_page(request: HttpRequest, user_id: int) -> HttpResponse:
    other_user = User.objects.filter(pk=user_id).select_related('profile').first()
    if not other_user or is_reserved_admin_username(other_user.get_username()):
        raise Http404("Пользователь не найден")
    if other_user.pk == request.user.pk:
        return redirect('core:messages')
    # Read receipts are driven by the client once messages actually enter the
    # viewport with an active tab, so the page load itself must not mark reads.
    messages_qs = get_message_history(request.user, other_user, mark_read=False)
    display_name = _community_display_name(other_user, getattr(other_user, 'profile', None))
    return render(
        request,
        'message_dialog.html',
        {
            'dialog_user': other_user,
            'dialog_display_name': display_name,
            'messages': [_message_payload(message, request.user) for message in messages_qs],
            'message_reactions': ALLOWED_MESSAGE_REACTIONS,
            **_seo_context(
                request,
                title=f'{display_name} - Сообщения - СКлад',
                description='История личной переписки в СКладе.',
                indexable=False,
                canonical_path=reverse('core:message-dialog', kwargs={'user_id': other_user.pk}),
            ),
        },
    )


@login_required
@ensure_csrf_cookie
def community_user_profile(request: HttpRequest, username: str) -> HttpResponse:
    if is_reserved_admin_username(username):
        raise Http404("РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РЅР°Р№РґРµРЅ")
    viewed_user = User.objects.filter(username__iexact=username).only('id', 'username').first()
    if viewed_user and viewed_user.pk == request.user.pk:
        return redirect('core:profile')
    profile_page = build_extended_profile_context(request.user, username)
    if not profile_page.get('found'):
        raise Http404("Пользователь не найден")
    profile_data = profile_page['profile']
    return render(
        request,
        'community_user_profile.html',
        {
            'profile_page': profile_page,
            'profile_nav_section': 'community',
            'profile_canonical_path': reverse('core:community-user-profile', kwargs={'username': profile_data['username']}),
            **_seo_context(
                request,
                title=f"{profile_data['display_name']} - профиль в СКлад",
                description='Публичный профиль пользователя раздела Люди в СКладе.',
                indexable=False,
                canonical_path=reverse('core:community-user-profile', kwargs={'username': profile_data['username']}),
            ),
        },
    )


def terms(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'terms.html',
        {
            'terms_version': django_settings.TERMS_VERSION,
            **_seo_context(
                request,
                title='Пользовательское соглашение - СКлад',
                description='Пользовательское соглашение сервиса СКлад и актуальная версия условий использования сайта.',
                indexable=True,
                canonical_path=reverse('core:terms'),
            ),
        },
    )


def about(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'info_placeholder.html',
        _seo_context(
            request,
            title='О нас - СКлад',
            description='Раздел находится в разработке.',
            indexable=False,
            canonical_path=reverse('core:about'),
        ),
    )


def contacts(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'info_placeholder.html',
        _seo_context(
            request,
            title='Контакты - СКлад',
            description='Раздел находится в разработке.',
            indexable=False,
            canonical_path=reverse('core:contacts'),
        ),
    )


def requisites(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'info_placeholder.html',
        _seo_context(
            request,
            title='Информация - СКлад',
            description='Раздел находится в разработке.',
            indexable=False,
            canonical_path=reverse('core:requisites'),
        ),
    )


def _public_news_payload(article: NewsArticle, request: HttpRequest) -> dict:
    cover_url = ''
    if article.cover:
        try:
            cover_url = request.build_absolute_uri(article.cover.url)
        except Exception:  # pragma: no cover - storage without a URL
            cover_url = ''
    return {
        'slug': article.slug,
        'title': article.title,
        'preview': article.preview,
        'full': article.body,
        'cover': cover_url,
        'published_at': article.publish_at.isoformat(),
    }


@ensure_csrf_cookie
def news(request: HttpRequest) -> HttpResponse:
    now = timezone.now()
    published = NewsArticle.objects.filter(is_published=True, publish_at__lte=now)
    context = _seo_context(
        request,
        title='Инструкции и новости проекта - СКлад',
        description='Инструкции по использованию СКлада, новости проекта, обновления функциональности и полезная информация о сервисе.',
        indexable=True,
        canonical_path=reverse('core:news'),
    )
    context['news_articles'] = [_public_news_payload(article, request) for article in published]
    return render(request, 'news.html', context)


@ensure_csrf_cookie
def reviews(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'reviews.html',
        _seo_context(
            request,
            title='Отзывы о проекте - СКлад',
            description='Отзывы пользователей о проекте СКлад, оценки сервиса и обратная связь о работе сайта.',
            indexable=True,
            canonical_path=reverse('core:reviews'),
        ),
    )


@require_GET
def robots_txt(request: HttpRequest) -> HttpResponse:
    sitemap_url = request.build_absolute_uri(reverse('sitemap'))
    lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /admin/',
        'Disallow: /studio/',
        'Disallow: /api/',
        'Disallow: /archive/',
        'Disallow: /profile/',
        'Disallow: /settings/',
        'Disallow: /messages/',
        'Disallow: /market/api/',
        f'Sitemap: {sitemap_url}',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')


@require_GET
@never_cache
def auth_status(request: HttpRequest) -> JsonResponse:
    if request.user.is_authenticated:
        return JsonResponse({'authenticated': True, 'username': request.user.get_username()})
    return JsonResponse({'authenticated': False})




@require_GET
def check_auth_availability(request: HttpRequest) -> JsonResponse:
    username = str(request.GET.get('username') or '').strip()
    email = str(request.GET.get('email') or '').strip()

    username_available = True
    email_available = True

    if username:
        username_available = (
            not is_reserved_admin_username(username)
            and not User.objects.filter(username__iexact=username).exists()
        )

    if email:
        email_norm = User.objects.normalize_email(email)
        email_available = not User.objects.filter(email__iexact=email_norm).exists()

    return JsonResponse({
        'success': True,
        'username_available': username_available,
        'email_available': email_available,
    })


@require_POST
def register_user(request: HttpRequest) -> JsonResponse:
    terms_accepted = str(request.POST.get('terms_accepted') or '').lower() in {'1', 'true', 'yes', 'on'}
    terms_version = str(request.POST.get('terms_version') or '').strip()
    if not terms_accepted or terms_version != django_settings.TERMS_VERSION:
        return JsonResponse(
            {'success': False, 'errors': {'terms': ['Для регистрации необходимо принять актуальную версию пользовательского соглашения.']}},
            status=400,
        )

    form = RegistrationForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'success': False, 'errors': form.errors}, status=400)

    with transaction.atomic():
        user = form.save()
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.mark_terms_accepted(ip=request.META.get('REMOTE_ADDR'))

    authenticated = authenticate(
        request,
        username=user.get_username(),
        password=form.cleaned_data.get('password1'),
    )
    if authenticated is None:
        return JsonResponse(
            {'success': False, 'errors': {'__all__': ['Не удалось создать сессию пользователя.']}},
            status=500,
        )
    login(request, authenticated)
    _touch_user_last_seen(authenticated)
    return JsonResponse({'success': True})


@require_POST
def login_user(request: HttpRequest) -> JsonResponse:
    form = LoginForm(request, data=request.POST)
    if form.is_valid():
        user = form.get_user()
        if is_reserved_admin_username(user.get_username()):
            return JsonResponse(
                {'success': False, 'errors': {'__all__': ['Пользователь не найден.']}},
                status=403,
            )
        profile = getattr(user, 'profile', None)
        if profile and profile.is_blocked:
            return JsonResponse(
                {'success': False, 'blocked': True, 'errors': {'__all__': [messages.blocked_message(profile)]}},
                status=403,
            )
        login(request, user)
        _touch_user_last_seen(user)
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'errors': form.errors}, status=400)


@login_required
@require_POST
def subscription_checkout(request: HttpRequest) -> HttpResponse:
    plan_code = str(request.POST.get('plan') or '').strip().lower()
    billing_period = str(request.POST.get('period') or '').strip().lower()
    wants_json = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )
    try:
        intent = subscriptions.create_checkout_intent(
            request.user,
            plan_code,
            billing_period,
        )
    except (subscriptions.SubscriptionLimitError, ValidationError) as exc:
        errors = exc.message_dict if hasattr(exc, 'message_dict') else {'__all__': exc.messages}
        return JsonResponse({'success': False, 'errors': errors}, status=400)
    except subscriptions.SubscriptionPlan.DoesNotExist:
        return JsonResponse({'success': False, 'errors': {'plan': ['Unknown subscription plan.']}}, status=404)
    if not wants_json:
        return redirect(intent.confirmation_url)
    return JsonResponse({
        'success': True,
        'provider': intent.provider,
        'payment_uuid': intent.payment_uuid,
        'subscription_id': intent.subscription_id,
        'confirmation_url': intent.confirmation_url,
        'redirect_url': intent.confirmation_url,
    })


@csrf_exempt
@require_POST
def yookassa_webhook(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': True, 'status': 'ignored'})

    event = str(payload.get('event') or '')
    if event not in {'payment.succeeded', 'payment.canceled', 'payment.waiting_for_capture'}:
        return JsonResponse({'ok': True, 'status': 'ignored'})

    payment_id = str((payload.get('object') or {}).get('id') or '').strip()
    if not payment_id:
        return JsonResponse({'ok': True, 'status': 'ignored'})

    payment_logger.info('YooKassa webhook received: event=%s payment_id=%s', event, payment_id)
    try:
        result = subscriptions.process_yookassa_payment(payment_id)
    except (subscriptions.PaymentUnavailable, subscriptions.PaymentGatewayError) as exc:
        errors = exc.message_dict if hasattr(exc, 'message_dict') else {'payment': exc.messages}
        payment_logger.warning('YooKassa webhook API/config error: payment_id=%s error=%s', payment_id, exc.__class__.__name__)
        return JsonResponse({'ok': False, 'errors': errors}, status=503)
    except Exception as exc:  # noqa: BLE001 - transient DB/API failures should be retried by YooKassa
        payment_logger.warning('YooKassa webhook processing failed: payment_id=%s error=%s', payment_id, exc.__class__.__name__)
        return JsonResponse({'ok': False, 'errors': {'payment': ['Temporary processing error.']}}, status=503)

    return JsonResponse({
        'ok': True,
        'status': result.status,
        'activated': result.activated,
        'message': result.message,
    })


@login_required
@require_GET
def subscription_payment_result(request: HttpRequest) -> HttpResponse:
    payment_uuid = str(request.GET.get('payment') or request.GET.get('payment_uuid') or '').strip()
    try:
        payment = SubscriptionPayment.objects.filter(internal_uuid=payment_uuid, user=request.user).select_related('tariff').first()
    except (ValueError, ValidationError):
        payment = None
    if payment is None:
        raise Http404('Payment not found')

    result_status = payment.status
    result_message = ''
    if payment.yookassa_payment_id:
        try:
            result = subscriptions.refresh_yookassa_payment_status(payment)
            if result.payment and result.payment.user_id == request.user.id:
                payment = result.payment
                result_status = result.status
                result_message = result.message
        except Exception as exc:  # noqa: BLE001 - render a safe error instead of trusting return redirect
            payment_logger.warning(
                'YooKassa return status check failed: payment_uuid=%s payment_id=%s error=%s',
                payment.internal_uuid,
                payment.yookassa_payment_id,
                exc.__class__.__name__,
            )
            result_status = 'error'
            result_message = 'Не удалось проверить статус платежа. Попробуйте обновить страницу позже.'

    return render(
        request,
        'subscription_payment_result.html',
        {
            'payment': payment,
            'result_status': result_status,
            'result_message': result_message,
            **_seo_context(
                request,
                title='Статус платежа - СКлад',
                description='Проверка статуса платежа подписки.',
                indexable=False,
                canonical_path=reverse('core:payment-result'),
            ),
        },
    )


@require_POST
def logout_user(request: HttpRequest) -> JsonResponse:
    logout(request)
    return JsonResponse({'success': True})


@login_required
@require_http_methods(["GET", "PATCH", "POST"])
def profile_api(request: HttpRequest) -> JsonResponse:
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == 'GET':
        return JsonResponse({
            'success': True,
            'profile': {
                'display_name': profile.display_name,
                'first': request.user.first_name,
                'last': request.user.last_name,
                'city': profile.avatar_meta.get('city', ''),
                'email': request.user.email,
                'link': profile.link,
                'interests': profile.avatar_meta.get('interests', ''),
                'privacy_level': profile.privacy_level,
                'avatar_data': profile.avatar_meta.get('avatar_data', ''),
                'avatar_pos': profile.avatar_meta.get('avatar_pos', {'x': 50, 'y': 50, 'scale': 100}),
                'background_image': profile.background_image,
            },
            'background': _profile_cover_payload(profile.background_image),
        })

    is_multipart = request.content_type and request.content_type.startswith('multipart/form-data')
    if is_multipart:
        payload = request.POST
    else:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}

    if is_multipart and ('background_image' in payload or 'background_file' in request.FILES):
        old_background = profile.background_image
        new_background_path = None
        try:
            if 'background_file' in request.FILES:
                new_background_path = _save_profile_cover_upload(request.user, request.FILES['background_file'])
                profile.background_image = new_background_path
            else:
                profile.background_image = ''
            profile.save(update_fields=['background_image'])
        except ValueError as exc:
            return JsonResponse(
                {'success': False, 'errors': {'background_image': [str(exc)]}},
                status=400,
            )
        except Exception:
            if new_background_path:
                _delete_profile_cover(new_background_path)
            raise

        if old_background and old_background != profile.background_image:
            _delete_profile_cover(old_background)
        background = _profile_cover_payload(profile.background_image)
        return JsonResponse({'success': True, 'background': background, 'background_image': profile.background_image})

    request.user.first_name = str(payload.get('first', request.user.first_name) or '')[:150]
    request.user.last_name = str(payload.get('last', request.user.last_name) or '')[:150]
    request.user.email = str(payload.get('email', request.user.email) or '')[:254]
    profile.link = str(payload.get('link', profile.link) or '')[:255]
    profile.privacy_level = str(payload.get('privacy_level', profile.privacy_level) or 'public')[:50]
    update_profile_fields = ['link', 'privacy_level', 'avatar_meta']
    old_background = profile.background_image
    new_background_path = None
    delete_old_background = False
    background_touched = 'background_image' in payload or 'background_file' in request.FILES
    if 'background_file' in request.FILES:
        try:
            new_background_path = _save_profile_cover_upload(request.user, request.FILES['background_file'])
        except ValueError as exc:
            return JsonResponse(
                {'success': False, 'errors': {'background_image': [str(exc)]}},
                status=400,
            )
        profile.background_image = new_background_path
        delete_old_background = bool(old_background and old_background != new_background_path)
        update_profile_fields.append('background_image')
    elif 'background_image' in payload:
        try:
            profile.background_image = validate_profile_background(str(payload.get('background_image') or ''))
        except ValueError:
            return JsonResponse(
                {'success': False, 'errors': {'background_image': ['Выберите стандартный фон или загрузите изображение.']}},
                status=400,
            )
        delete_old_background = not profile.background_image and bool(old_background)
        update_profile_fields.append('background_image')

    meta = profile.avatar_meta if isinstance(profile.avatar_meta, dict) else {}
    meta['city'] = str(payload.get('city', meta.get('city', '')) or '')[:255]
    meta['interests'] = str(payload.get('interests', meta.get('interests', '')) or '')[:4000]
    meta['avatar_data'] = str(payload.get('avatar_data', meta.get('avatar_data', '')) or '')
    avatar_pos = payload.get('avatar_pos', meta.get('avatar_pos', {'x': 50, 'y': 50, 'scale': 100}))
    if isinstance(avatar_pos, dict):
        meta['avatar_pos'] = {
            'x': max(0, min(100, float(avatar_pos.get('x', 50) or 50))),
            'y': max(0, min(100, float(avatar_pos.get('y', 50) or 50))),
            'scale': max(100, min(180, float(avatar_pos.get('scale', 100) or 100))),
        }
    profile.avatar_meta = meta

    try:
        request.user.save(update_fields=['first_name', 'last_name', 'email'])
        profile.save(update_fields=update_profile_fields)
    except Exception:
        if new_background_path:
            _delete_profile_cover(new_background_path)
        raise
    if delete_old_background:
        _delete_profile_cover(old_background)
    background = _profile_cover_payload(profile.background_image) if background_touched else None
    return JsonResponse({'success': True, 'background': background, 'background_image': profile.background_image})


COMMUNITY_PAGE_SIZE = 12
COMMUNITY_ONLINE_WINDOW_SECONDS = 5 * 60


def _touch_user_last_seen(user: User) -> None:
    Profile.objects.update_or_create(
        user=user,
        defaults={'last_seen_at': timezone.now()},
    )


def _community_display_name(user: User, profile: Profile | None = None) -> str:
    if profile and profile.display_name:
        return profile.display_name
    full_name = user.get_full_name().strip()
    return full_name or user.get_username()


def _community_presence_payload(profile: Profile | None) -> dict:
    last_seen_at = profile.last_seen_at if profile else None
    if not last_seen_at:
        return {'is_online': False, 'label': 'Активность пока неизвестна'}

    now = timezone.localtime(timezone.now())
    local_seen = timezone.localtime(last_seen_at)
    if (now - local_seen).total_seconds() <= COMMUNITY_ONLINE_WINDOW_SECONDS:
        return {'is_online': True, 'label': 'Онлайн'}

    time_label = local_seen.strftime('%H:%M')
    if local_seen.date() == now.date():
        label = f'Заходил сегодня в {time_label}'
    elif local_seen.date() == (now - timedelta(days=1)).date():
        label = f'Заходил вчера в {time_label}'
    else:
        label = f"Заходил {local_seen.strftime('%d.%m.%Y')} в {time_label}"
    return {'is_online': False, 'label': label}


def _community_can_view_details(viewer: User, user: User, profile: Profile | None = None) -> bool:
    if viewer.pk == user.pk:
        return True
    if viewer.is_superuser:
        return True
    if profile and profile.is_hidden:
        return False
    privacy = (profile.privacy_level if profile else 'public') or 'public'
    if privacy == 'public':
        return True
    if privacy == 'private':
        return False
    return get_relationship_status(viewer, user)['status'] == Friendship.Status.ACCEPTED


def _community_is_private_profile(user: User, profile: Profile | None = None) -> bool:
    profile = profile if profile is not None else getattr(user, 'profile', None)
    return ((profile.privacy_level if profile else 'public') or 'public') == 'private'


def _community_is_hidden_profile(user: User, profile: Profile | None = None) -> bool:
    profile = profile if profile is not None else getattr(user, 'profile', None)
    # Administratively blocked profiles are treated like hidden ones so they
    # never surface in the public people search or community listings.
    return bool(profile and (profile.is_hidden or profile.is_blocked))


def _community_visible_users(queryset):
    admin_login = configured_admin_login()
    if admin_login:
        queryset = queryset.exclude(username__iexact=admin_login)
    return (
        queryset
        .exclude(profile__is_hidden=True)
        .exclude(profile__is_blocked=True)
        .filter(Q(profile__isnull=True) | ~Q(profile__privacy_level='private'))
    )


def _community_user_payload(user: User, viewer: User, relation_cache: dict[int, dict] | None = None) -> dict:
    profile = getattr(user, 'profile', None)
    meta = profile.avatar_meta if profile and isinstance(profile.avatar_meta, dict) else {}
    relationship = relation_cache.get(user.pk) if relation_cache is not None else get_relationship_status(viewer, user)
    status = relationship.get('status') or 'none'
    requester_id = relationship.get('requester_id')
    if status == Friendship.Status.PENDING and requester_id == viewer.pk:
        friendship_state = 'outgoing'
    elif status == Friendship.Status.PENDING:
        friendship_state = 'incoming'
    elif status == Friendship.Status.ACCEPTED:
        friendship_state = 'accepted'
    else:
        friendship_state = 'none'
    can_view_details = _community_can_view_details(viewer, user, profile)
    return {
        'id': user.pk,
        'username': user.get_username(),
        'display_name': _community_display_name(user, profile),
        'avatar_data': meta.get('avatar_data', '') if profile else '',
        'avatar_pos': meta.get('avatar_pos', {'x': 50, 'y': 50, 'scale': 100}) if profile else {'x': 50, 'y': 50, 'scale': 100},
        'city': meta.get('city', '') if can_view_details else '',
        'interests': meta.get('interests', '') if can_view_details else '',
        'presence': _community_presence_payload(profile),
        'friendship_state': friendship_state,
        'profile_url': reverse('core:community-user-profile', kwargs={'username': user.get_username()}),
        'message_url': reverse('core:message-dialog', kwargs={'user_id': user.pk}),
    }


def _community_relation_payload(relation: Friendship, viewer: User) -> dict:
    other = relation.user_high if relation.user_low_id == viewer.pk else relation.user_low
    return {
        'id': relation.pk,
        'created_at': relation.created_at.isoformat(),
        'updated_at': relation.updated_at.isoformat(),
        'user': _community_user_payload(other, viewer),
    }


def _community_relation_is_visible(relation: Friendship, viewer: User) -> bool:
    other = relation.user_high if relation.user_low_id == viewer.pk else relation.user_low
    return not (_community_is_private_profile(other) or _community_is_hidden_profile(other))


def _community_counts(user: User) -> dict:
    incoming_count = sum(1 for relation in get_incoming_requests(user).select_related('user_low__profile', 'user_high__profile') if _community_relation_is_visible(relation, user))
    outgoing_count = sum(1 for relation in get_outgoing_requests(user).select_related('user_low__profile', 'user_high__profile') if _community_relation_is_visible(relation, user))
    friend_count = _community_visible_users(get_friends(user)).count()
    return {
        'friends': friend_count,
        'incoming': incoming_count,
        'outgoing': outgoing_count,
    }


def _community_incoming_request_summary(user: User) -> dict:
    relations = list(get_incoming_requests(user).select_related('user_low__profile', 'user_high__profile', 'requester').order_by('-created_at', '-id'))
    relations = [relation for relation in relations if _community_relation_is_visible(relation, user)]
    latest_at = relations[0].created_at if relations else None
    return {
        'total': len(relations),
        'latest_at': latest_at,
        'requests': relations,
    }


@login_required
@require_GET
def community_summary_api(request: HttpRequest) -> JsonResponse:
    friends = list(_community_visible_users(get_friends(request.user)).select_related('profile')[:7])
    payload_friends = [_community_user_payload(user, request.user) for user in friends[:6]]
    counts = _community_counts(request.user)
    return JsonResponse({
        'success': True,
        'counts': counts,
        'friends_preview': payload_friends,
        'friends_extra': max(0, counts['friends'] - len(payload_friends)),
    })


@login_required
@require_GET
def community_unread_requests_api(request: HttpRequest) -> JsonResponse:
    summary = _community_incoming_request_summary(request.user)
    return JsonResponse({
        'success': True,
        'user_id': request.user.pk,
        'total': summary['total'],
        'latest_at': summary['latest_at'].isoformat() if summary['latest_at'] else None,
        'requests': [
            {
                'id': relation.pk,
                'created_at': relation.created_at.isoformat(),
                'user': _community_user_payload(
                    relation.user_high if relation.user_low_id == request.user.pk else relation.user_low,
                    request.user,
                ),
            }
            for relation in summary['requests']
        ],
    })


@login_required
@require_GET
def community_search_api(request: HttpRequest) -> JsonResponse:
    query = str(request.GET.get('q') or '').strip()
    try:
        page = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page = 1

    matches = _community_visible_users(User.objects.all()).exclude(pk=request.user.pk).select_related('profile')
    if len(query) >= 2:
        matches = matches.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(profile__display_name__icontains=query)
        )
    matches = matches.distinct().order_by('username', 'id')
    total = matches.count()
    page_size = COMMUNITY_PAGE_SIZE
    num_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, num_pages)
    users = list(matches[(page - 1) * page_size: page * page_size])
    return JsonResponse({
        'success': True,
        'query': query,
        'count': total,
        'page': page,
        'num_pages': num_pages,
        'users': [_community_user_payload(user, request.user) for user in users],
    })


@login_required
@require_GET
def community_friends_api(request: HttpRequest) -> JsonResponse:
    query = str(request.GET.get('q') or '').strip()
    friends = _community_visible_users(get_friends(request.user)).select_related('profile')
    if query:
        friends = friends.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(profile__display_name__icontains=query)
        ).distinct()
    users = list(friends)
    return JsonResponse({
        'success': True,
        'count': len(users),
        'users': [_community_user_payload(user, request.user) for user in users],
    })


@login_required
@require_GET
def community_requests_api(request: HttpRequest) -> JsonResponse:
    incoming = list(get_incoming_requests(request.user).select_related('user_low__profile', 'user_high__profile', 'requester'))
    outgoing = list(get_outgoing_requests(request.user).select_related('user_low__profile', 'user_high__profile', 'requester'))
    incoming = [relation for relation in incoming if _community_relation_is_visible(relation, request.user)]
    outgoing = [relation for relation in outgoing if _community_relation_is_visible(relation, request.user)]
    return JsonResponse({
        'success': True,
        'counts': _community_counts(request.user),
        'incoming': [_community_relation_payload(relation, request.user) for relation in incoming],
        'outgoing': [_community_relation_payload(relation, request.user) for relation in outgoing],
    })


@login_required
@require_POST
def community_friendship_action_api(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    action = str(payload.get('action') or '').strip()
    target_id = payload.get('target_id')
    target = User.objects.filter(pk=target_id).first()
    if target and is_reserved_admin_username(target.get_username()):
        target = None
    if not target:
        return JsonResponse({'success': False, 'error': 'Пользователь не найден.'}, status=404)
    if _community_is_private_profile(target) or _community_is_hidden_profile(target):
        return JsonResponse({'success': False, 'error': 'Пользователь не найден.'}, status=404)

    try:
        if action == 'send':
            relation = send_request(request.user, target)
            message = 'Заявка отправлена.'
        elif action == 'accept':
            relation = accept_request(request.user, target)
            message = 'Пользователь добавлен в друзья.'
        elif action == 'reject':
            relation = reject_request(request.user, target)
            message = 'Заявка отклонена.'
        elif action == 'cancel':
            cancel_request(request.user, target)
            relation = None
            message = 'Заявка отменена.'
        elif action == 'remove':
            remove_friend(request.user, target)
            relation = None
            message = 'Пользователь удалён из друзей.'
        else:
            return JsonResponse({'success': False, 'error': 'Неизвестное действие.'}, status=400)
    except FriendshipError as exc:
        return JsonResponse({'success': False, 'error': str(exc), 'code': exc.code}, status=400)

    return JsonResponse({
        'success': True,
        'message': message,
        'relationship': {
            'status': get_relationship_status(request.user, target)['status'],
            'requester_id': get_relationship_status(request.user, target)['requester_id'],
        },
        'target': _community_user_payload(target, request.user),
        'counts': _community_counts(request.user),
        'relation_id': relation.pk if relation else None,
    })


def _message_user_payload(user: User) -> dict:
    profile = getattr(user, 'profile', None)
    return {
        'id': user.pk,
        'username': user.get_username(),
        'display_name': _community_display_name(user, profile),
    }


def _message_reactions_payload(message, viewer: User) -> tuple[list[dict], str]:
    if getattr(message, 'is_deleted', False) or getattr(message, 'deleted_at', None):
        return [], ''
    grouped = {
        reaction: {'reaction': reaction, 'count': 0, 'selected': False}
        for reaction in ALLOWED_MESSAGE_REACTIONS
    }
    viewer_reaction = ''
    for item in message.reactions.all():
        if item.reaction not in grouped:
            continue
        grouped[item.reaction]['count'] += 1
        if item.user_id == viewer.pk:
            grouped[item.reaction]['selected'] = True
            viewer_reaction = item.reaction
    return [item for item in grouped.values() if item['count']], viewer_reaction


def _format_file_size(size) -> str:
    """Human-readable file size, e.g. «1.4 МБ»."""
    try:
        size = int(size)
    except (TypeError, ValueError):
        return ''
    if size < 1024:
        return f'{size} Б'
    for unit in ('КБ', 'МБ', 'ГБ'):
        size /= 1024.0
        if size < 1024 or unit == 'ГБ':
            return f'{size:.1f} {unit}'.replace('.0 ', ' ')
    return ''


def _attachment_payload(message) -> dict | None:
    """Serialise a message attachment (or ``None`` when there is none)."""
    if not message.attachment:
        return None
    try:
        url = message.attachment.url
    except Exception:  # noqa: BLE001 - storage may raise on a missing file
        url = ''
    return {
        'url': url,
        'name': message.attachment_name or 'Файл',
        'size': message.attachment_size,
        'size_display': _format_file_size(message.attachment_size),
        'kind': message.attachment_kind or 'file',
        'is_image': message.attachment_kind == 'image',
        'content_type': message.attachment_content_type or '',
    }


def _message_payload(message, viewer: User) -> dict:
    reactions, viewer_reaction = _message_reactions_payload(message, viewer)
    is_deleted = bool(message.is_deleted)
    return {
        'id': message.pk,
        'sender': _message_user_payload(message.sender),
        'recipient': _message_user_payload(message.recipient),
        'text': 'Сообщение удалено' if is_deleted else message.text,
        'raw_text': '' if is_deleted else message.text,
        'sent_at': message.sent_at.isoformat(),
        'sent_at_display': timezone.localtime(message.sent_at).strftime('%d.%m.%Y %H:%M'),
        'edited_at': message.edited_at.isoformat() if message.edited_at else None,
        'is_edited': bool(message.edited_at and not is_deleted),
        'is_deleted': is_deleted,
        'is_read': message.is_read,
        'read_at': message.read_at.isoformat() if message.read_at else None,
        'is_outgoing': message.sender_id == viewer.pk,
        'can_edit': message.sender_id == viewer.pk and not is_deleted,
        'can_delete': message.sender_id == viewer.pk and not is_deleted,
        'can_react': not is_deleted,
        'reactions': reactions,
        'viewer_reaction': viewer_reaction,
        'attachment': None if is_deleted else _attachment_payload(message),
    }


@login_required
@require_GET
def message_dialogs_api(request: HttpRequest) -> JsonResponse:
    dialogs = []
    for dialog in get_dialogs(request.user):
        latest_message = dialog['latest_message']
        dialogs.append({
            'user': _message_user_payload(dialog['user']),
            'latest_message': _message_payload(latest_message, request.user),
            'latest_at': dialog['latest_at'].isoformat(),
            'unread_count': dialog['unread_count'],
            'message_count': dialog['message_count'],
        })
    return JsonResponse({'success': True, 'dialogs': dialogs})


@login_required
@require_GET
def message_unread_api(request: HttpRequest) -> JsonResponse:
    summary = get_unread_summary(request.user)
    return JsonResponse({
        'success': True,
        'user_id': request.user.pk,
        'total': summary['total'],
        'latest_at': summary['latest_at'].isoformat() if summary['latest_at'] else None,
        'senders': [
            {
                'user': _message_user_payload(item['user']),
                'count': item['count'],
                'latest_at': item['latest_at'].isoformat(),
            }
            for item in summary['senders']
        ],
    })


@login_required
@require_GET
def message_history_api(request: HttpRequest, user_id: int) -> JsonResponse:
    other_user = User.objects.filter(pk=user_id).select_related('profile').first()
    if not other_user or is_reserved_admin_username(other_user.get_username()):
        return JsonResponse({'success': False, 'error': 'Пользователь не найден.'}, status=404)
    try:
        # Polling/refreshes must not mark messages read; that is an explicit,
        # viewport-driven action handled by message_mark_read_api.
        messages_qs = get_message_history(request.user, other_user, mark_read=False)
    except MessageError as exc:
        return JsonResponse({'success': False, 'error': str(exc), 'code': exc.code}, status=400)
    return JsonResponse({
        'success': True,
        'user': _message_user_payload(other_user),
        'messages': [_message_payload(message, request.user) for message in messages_qs],
    })


@login_required
@require_POST
def message_mark_read_api(request: HttpRequest, user_id: int) -> JsonResponse:
    other_user = User.objects.filter(pk=user_id).first()
    if not other_user or is_reserved_admin_username(other_user.get_username()):
        return JsonResponse({'success': False, 'error': 'Пользователь не найден.'}, status=404)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    raw_ids = payload.get('message_ids')
    message_ids = raw_ids if isinstance(raw_ids, list) else None
    try:
        marked = mark_messages_read(request.user, other_user, message_ids)
    except MessageError as exc:
        return JsonResponse({'success': False, 'error': str(exc), 'code': exc.code}, status=400)
    return JsonResponse({'success': True, 'marked': marked})


@login_required
@require_POST
def message_send_api(request: HttpRequest) -> JsonResponse:
    content_type = request.content_type or ''
    attachment = None
    if content_type.startswith('multipart/form-data'):
        recipient_id = request.POST.get('recipient_id')
        text = request.POST.get('text', '')
        attachment = request.FILES.get('attachment')
    else:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        recipient_id = payload.get('recipient_id')
        text = payload.get('text', '')
    recipient = User.objects.filter(pk=recipient_id).select_related('profile').first()
    if not recipient or is_reserved_admin_username(recipient.get_username()):
        return JsonResponse({'success': False, 'error': 'Получатель не найден.'}, status=404)
    try:
        message = send_message(request.user, recipient, text, attachment=attachment)
    except MessageError as exc:
        return JsonResponse({'success': False, 'error': str(exc), 'code': exc.code}, status=400)
    except ValidationError as exc:
        return JsonResponse({'success': False, 'error': '; '.join(exc.messages)}, status=400)
    return JsonResponse({'success': True, 'message': _message_payload(message, request.user)}, status=201)


@login_required
@require_http_methods(["PATCH", "POST"])
def message_edit_api(request: HttpRequest, message_id: int) -> JsonResponse:
    message = DirectMessage.objects.filter(pk=message_id).select_related('sender', 'recipient').first()
    if not message:
        return JsonResponse({'success': False, 'error': 'Сообщение не найдено.'}, status=404)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    try:
        updated_message = edit_message(request.user, message, payload.get('text', ''))
        updated_message = DirectMessage.objects.select_related('sender', 'recipient').prefetch_related('reactions').get(pk=updated_message.pk)
    except MessageError as exc:
        return JsonResponse({'success': False, 'error': str(exc), 'code': exc.code}, status=403 if exc.code == 'not_sender' else 400)
    except ValidationError as exc:
        return JsonResponse({'success': False, 'error': '; '.join(exc.messages)}, status=400)
    return JsonResponse({'success': True, 'message': _message_payload(updated_message, request.user)})


@login_required
@require_POST
def message_delete_api(request: HttpRequest, message_id: int) -> JsonResponse:
    message = DirectMessage.objects.filter(pk=message_id).select_related('sender', 'recipient').first()
    if not message:
        return JsonResponse({'success': False, 'error': 'Сообщение не найдено.'}, status=404)
    try:
        updated_message = delete_message(request.user, message)
        updated_message = DirectMessage.objects.select_related('sender', 'recipient').prefetch_related('reactions').get(pk=updated_message.pk)
    except MessageError as exc:
        return JsonResponse({'success': False, 'error': str(exc), 'code': exc.code}, status=403 if exc.code == 'not_sender' else 400)
    return JsonResponse({'success': True, 'message': _message_payload(updated_message, request.user)})


@login_required
@require_POST
def message_reaction_api(request: HttpRequest, message_id: int) -> JsonResponse:
    message = DirectMessage.objects.filter(pk=message_id).select_related('sender', 'recipient').first()
    if not message:
        return JsonResponse({'success': False, 'error': 'Сообщение не найдено.'}, status=404)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    try:
        updated_message = set_message_reaction(request.user, message, payload.get('reaction'))
        updated_message = DirectMessage.objects.select_related('sender', 'recipient').prefetch_related('reactions').get(pk=updated_message.pk)
    except MessageError as exc:
        return JsonResponse({'success': False, 'error': str(exc), 'code': exc.code}, status=403 if exc.code == 'not_participant' else 400)
    except ValidationError as exc:
        return JsonResponse({'success': False, 'error': '; '.join(exc.messages)}, status=400)
    return JsonResponse({'success': True, 'message': _message_payload(updated_message, request.user)})


@login_required
@require_http_methods(["GET", "PUT"])
@never_cache
def archive_state_api(request: HttpRequest) -> JsonResponse:
    state, _ = ArchiveState.objects.get_or_create(user=request.user, defaults={'data': {'rubrics': []}})
    if request.method == 'GET':
        state_data = state.data if isinstance(state.data, dict) else {'rubrics': []}
        if _normalize_public_rubric_state(state_data):
            state.data = state_data
            state.save(update_fields=['data', 'updated_at'])
        return JsonResponse({'success': True, 'state': state_data})

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'success': False, 'errors': {'state': ['Некорректный JSON']}}, status=400)

    state_payload = payload.get('state', payload)
    if not isinstance(state_payload, dict):
        return JsonResponse({'success': False, 'errors': {'state': ['Ожидается объект состояния']}}, status=400)

    _normalize_public_rubric_state(state_payload)
    try:
        subscriptions.assert_archive_state_within_limit(
            request.user,
            state_payload,
            state.data if isinstance(state.data, dict) else {'rubrics': []},
        )
    except subscriptions.SubscriptionLimitError as exc:
        return JsonResponse({'success': False, 'errors': exc.message_dict}, status=400)
    state.data = state_payload
    state.save(update_fields=['data', 'updated_at'])

    profile, _ = Profile.objects.get_or_create(user=request.user)
    rubrics = state_payload.get('rubrics') if isinstance(state_payload.get('rubrics'), list) else []
    existing_rubrics = {str(item.pk): item for item in Rubric.objects.filter(profile=profile)}
    for raw_rubric in rubrics:
        if not isinstance(raw_rubric, dict):
            continue
        db_rubric = existing_rubrics.get(str(raw_rubric.get('id') or '').strip())
        if not db_rubric:
            continue
        db_rubric.is_public = _coerce_bool(raw_rubric.get('publicEnabled'))
        db_rubric.public_slug = str(raw_rubric.get('publicSlug') or '')[:255]
        db_rubric.save(update_fields=['is_public', 'public_slug', 'updated_at'])
    return JsonResponse({'success': True})


@login_required
@require_GET
@never_cache
def list_rubrics(request: HttpRequest) -> JsonResponse:
    profile, _ = Profile.objects.get_or_create(user=request.user)
    rubrics = list(Rubric.objects.filter(profile=profile).values('id', 'name', 'slug', 'is_public', 'public_slug', 'is_text_mode', 'field_schema'))
    return JsonResponse({'success': True, 'rubrics': rubrics})


@login_required
@require_GET
@never_cache
def list_rubric_files(request: HttpRequest, rubric_id: int) -> JsonResponse:
    files = list(
        ArchiveFile.objects.filter(rubric_id=rubric_id, owner=request.user).values('id', 'rubric_id', 'title', 'status', 'data', 'created_at', 'updated_at')
    )
    return JsonResponse({'success': True, 'files': files})


@login_required
@require_GET
@never_cache
def export_rubric(request: HttpRequest, rubric_id: str, export_format: str) -> HttpResponse:
    state, _ = ArchiveState.objects.get_or_create(user=request.user, defaults={'data': {'rubrics': []}})
    state_data = state.data if isinstance(state.data, dict) else {'rubrics': []}
    rubric = exporters.find_rubric(state_data, rubric_id)
    if rubric is None:
        return JsonResponse({'success': False, 'errors': {'rubric': ['Рубрика не найдена.']}}, status=404)

    rubric_name = str(rubric.get('name') or 'rubric')
    export_format = str(export_format or '').strip().lower()
    if export_format == 'xlsx':
        content = exporters.build_xlsx(rubric, FILE_STATUS_LABELS)
        filename = exporters.safe_filename(rubric_name, 'xlsx')
        return exporters.file_response(
            content,
            filename,
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    if export_format == 'pdf':
        content = exporters.build_pdf(rubric, FILE_STATUS_LABELS)
        filename = exporters.safe_filename(rubric_name, 'pdf')
        return exporters.file_response(content, filename, 'application/pdf')
    return JsonResponse({'success': False, 'errors': {'format': ['Неподдерживаемый формат экспорта.']}}, status=400)


@login_required
@require_POST
@never_cache
def create_rubric(request: HttpRequest) -> JsonResponse:
    form = RubricForm(request.POST)
    if form.is_valid():
        rubric = form.save(commit=False)
        # «Аукцион» is a reserved system rubric managed by the platform; users
        # cannot create a regular rubric that shadows its name or slug.
        if rubric.slug == 'auction' or (rubric.name or '').strip().casefold() == 'аукцион':
            return JsonResponse({'success': False, 'errors': {'name': ['Название «Аукцион» зарезервировано для системной рубрики.']}}, status=400)
        profile, _ = Profile.objects.get_or_create(user=request.user)
        rubric.profile = profile
        rubric.is_system = False
        rubric.save()
        return JsonResponse({'success': True, 'rubric_id': rubric.pk})
    return JsonResponse({'success': False, 'errors': form.errors}, status=400)


@login_required
@require_http_methods(["POST", "PATCH"])
@never_cache
def create_archive_file(request: HttpRequest) -> JsonResponse:
    data = request.POST
    if request.method == 'PATCH':
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        data = payload

    form = ArchiveFileForm(data)
    if form.is_valid():
        archive_file = form.save(commit=False)
        if archive_file.rubric.profile.user != request.user:
            return JsonResponse({'success': False, 'errors': {'rubric': ['Недостаточно прав для добавления файла.']}}, status=403)
        try:
            subscriptions.assert_can_create_archive_file(request.user)
        except subscriptions.SubscriptionLimitError as exc:
            return JsonResponse({'success': False, 'errors': exc.message_dict}, status=400)
        archive_file.owner = request.user
        archive_file.update_signatures()

        duplicate_title = (
            ArchiveFile.objects.filter(owner=request.user, normalized_title=archive_file.normalized_title)
            .exclude(pk=archive_file.pk)
            .first()
        )
        if duplicate_title:
            logger.warning("Duplicate archive title blocked for user %s: %s", request.user.pk, archive_file.title)
            return JsonResponse({'success': False, 'errors': {'title': [messages.DUPLICATE_TITLE_ERROR.format(id=duplicate_title.pk)]}}, status=400)

        payload_hash = moderation.compute_payload_hash(archive_file.data)
        if payload_hash:
            duplicate_hash = None
            for candidate in ArchiveFile.objects.filter(owner=request.user).exclude(pk=archive_file.pk).only("pk", "data"):
                if moderation.compute_payload_hash(candidate.data) == payload_hash:
                    duplicate_hash = candidate
                    break
            if duplicate_hash:
                logger.warning(
                    "Duplicate archive content blocked for user %s: file %s matches %s",
                    request.user.pk,
                    archive_file.title,
                    duplicate_hash.pk,
                )
                return JsonResponse({'success': False, 'errors': {'__all__': [messages.DUPLICATE_CONTENT_ERROR.format(id=duplicate_hash.pk)]}}, status=400)

        try:
            archive_file.full_clean()
        except ValidationError as exc:
            return JsonResponse({'success': False, 'errors': exc.message_dict}, status=400)
        archive_file.save()
        return JsonResponse({'success': True, 'file_id': archive_file.pk})
    return JsonResponse({'success': False, 'errors': form.errors}, status=400)


@login_required
@require_http_methods(["PATCH"])
@never_cache
def update_archive_file(request: HttpRequest, file_id: int) -> JsonResponse:
    archive_file = ArchiveFile.objects.filter(id=file_id, owner=request.user).first()
    if not archive_file:
        return JsonResponse({'success': False, 'errors': {'file': ['Файл не найден']}}, status=404)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    if 'title' in payload:
        archive_file.title = str(payload.get('title') or '')
    if 'status' in payload:
        archive_file.status = _normalize_file_status(payload.get('status'))
    if 'data' in payload and isinstance(payload.get('data'), dict):
        archive_file.data = payload.get('data')
    try:
        archive_file.full_clean()
    except ValidationError as exc:
        return JsonResponse({'success': False, 'errors': exc.message_dict}, status=400)
    archive_file.save()
    return JsonResponse({'success': True})


@login_required
@require_POST
@never_cache
def move_archive_file(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    file_id = str(payload.get('file_id') or '').strip()
    source_rubric_id = str(payload.get('source_rubric_id') or '').strip()
    target_rubric_id = str(payload.get('target_rubric_id') or '').strip()

    if not file_id:
        return JsonResponse({'success': False, 'errors': {'file_id': ['Не указан файл для переноса.']}}, status=400)
    if not source_rubric_id:
        return JsonResponse({'success': False, 'errors': {'source_rubric_id': ['Не указана текущая рубрика файла.']}}, status=400)
    if not target_rubric_id:
        return JsonResponse({'success': False, 'errors': {'target_rubric_id': ['Не указана рубрика назначения.']}}, status=400)
    if source_rubric_id == target_rubric_id:
        return JsonResponse({'success': False, 'errors': {'target_rubric_id': ['Файл уже находится в выбранной рубрике.']}}, status=400)

    system_ids = _system_rubric_ids(request.user)
    if target_rubric_id in system_ids:
        return JsonResponse({'success': False, 'errors': {'target_rubric_id': ['В системную рубрику «Аукцион» нельзя переместить карточку вручную.']}}, status=400)
    if source_rubric_id in system_ids:
        return JsonResponse({'success': False, 'errors': {'source_rubric_id': ['Карточки системной рубрики «Аукцион» нельзя перемещать вручную.']}}, status=400)

    state, _ = ArchiveState.objects.get_or_create(user=request.user, defaults={'data': {'rubrics': []}})
    state_data = state.data if isinstance(state.data, dict) else {'rubrics': []}
    rubrics = state_data.get('rubrics')
    if not isinstance(rubrics, list):
        rubrics = []
        state_data['rubrics'] = rubrics

    source_rubric = None
    target_rubric = None
    for rubric in rubrics:
        if not isinstance(rubric, dict):
            continue
        rubric_id = str(rubric.get('id') or '').strip()
        if rubric_id == source_rubric_id:
            source_rubric = rubric
        if rubric_id == target_rubric_id:
            target_rubric = rubric

    if source_rubric is None:
        return JsonResponse({'success': False, 'errors': {'source_rubric_id': ['Исходная рубрика не найдена.']}}, status=404)
    if target_rubric is None:
        return JsonResponse({'success': False, 'errors': {'target_rubric_id': ['Рубрика назначения не найдена.']}}, status=404)

    source_files = source_rubric.get('files')
    target_files = target_rubric.get('files')
    if not isinstance(source_files, list):
        source_files = []
        source_rubric['files'] = source_files
    if not isinstance(target_files, list):
        target_files = []
        target_rubric['files'] = target_files

    moved_file = None
    for index, candidate in enumerate(source_files):
        if isinstance(candidate, dict) and str(candidate.get('id') or '').strip() == file_id:
            moved_file = source_files.pop(index)
            break

    if moved_file is None:
        return JsonResponse({'success': False, 'errors': {'file_id': ['Файл не найден в указанной рубрике.']}}, status=404)

    moved_file['updatedAt'] = int(timezone.now().timestamp() * 1000)
    target_files.insert(0, moved_file)
    state.data = state_data
    state.save(update_fields=['data', 'updated_at'])

    return JsonResponse({
        'success': True,
        'state': state.data,
        'file_id': file_id,
        'source_rubric_id': source_rubric_id,
        'target_rubric_id': target_rubric_id,
    })


def _normalize_archive_file_refs(raw_items) -> tuple[list[dict[str, str]], dict[str, list[str]]]:
    if not isinstance(raw_items, list):
        return [], {'items': ['Ожидается список файлов для обработки.']}

    normalized: list[dict[str, str]] = []
    errors: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()

    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            errors.setdefault('items', []).append(f'Элемент #{index + 1} имеет некорректный формат.')
            continue

        file_id = str(raw_item.get('file_id') or '').strip()
        source_rubric_id = str(raw_item.get('source_rubric_id') or '').strip()
        if not file_id or not source_rubric_id:
            errors.setdefault('items', []).append(f'Элемент #{index + 1} должен содержать file_id и source_rubric_id.')
            continue

        key = (source_rubric_id, file_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            'file_id': file_id,
            'source_rubric_id': source_rubric_id,
        })

    if not normalized and 'items' not in errors:
        errors['items'] = ['Не выбраны файлы для обработки.']
    return normalized, errors


def _system_rubric_ids(user) -> set[str]:
    """DB ids (as strings) of the user's system rubrics, e.g. «Аукцион».

    JSON-state rubric ids match the DB Rubric pk for DB-backed rubrics, so this
    lets the JSON-state endpoints enforce system-rubric immutability.
    """
    profile = Profile.objects.filter(user=user).first()
    if profile is None:
        return set()
    return {
        str(pk)
        for pk in Rubric.objects.filter(profile=profile, is_system=True).values_list('id', flat=True)
    }


def _card_active_lot_error(user, file_id: str) -> str | None:
    """Return a deletion-block message if the DB card has a live auction lot."""
    if not str(file_id).isdigit():
        return None
    card = ArchiveFile.objects.filter(pk=int(file_id), owner=user).first()
    if card is None:
        return None
    try:
        from auction.services import card_active_lot
    except Exception:  # pragma: no cover - auction app optional
        return None
    lot = card_active_lot(card)
    if lot is None:
        return None
    return (
        'Нельзя удалить карточку: товар участвует в активных торгах '
        f'(лот #{lot.pk}). Сначала завершите или отмените лот.'
    )


def _get_archive_state_for_user(user) -> tuple[ArchiveState, dict, list]:
    state, _ = ArchiveState.objects.get_or_create(user=user, defaults={'data': {'rubrics': []}})
    state_data = state.data if isinstance(state.data, dict) else {'rubrics': []}
    rubrics = state_data.get('rubrics')
    if not isinstance(rubrics, list):
        rubrics = []
        state_data['rubrics'] = rubrics
    return state, state_data, rubrics


@login_required
@require_POST
@never_cache
def bulk_delete_archive_files(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    items, errors = _normalize_archive_file_refs(payload.get('items'))
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    state, state_data, rubrics = _get_archive_state_for_user(request.user)
    rubric_map = {
        str(rubric.get('id') or '').strip(): rubric
        for rubric in rubrics
        if isinstance(rubric, dict)
    }

    deleted_ids: list[str] = []
    item_errors: dict[str, list[str]] = {}

    for item in items:
        file_id = item['file_id']
        source_rubric_id = item['source_rubric_id']
        rubric = rubric_map.get(source_rubric_id)
        if rubric is None:
            item_errors[file_id] = ['Исходная рубрика не найдена.']
            continue

        lot_block = _card_active_lot_error(request.user, file_id)
        if lot_block:
            item_errors[file_id] = [lot_block]
            continue

        source_files = rubric.get('files')
        if not isinstance(source_files, list):
            source_files = []
            rubric['files'] = source_files

        removed = False
        for index, candidate in enumerate(source_files):
            if isinstance(candidate, dict) and str(candidate.get('id') or '').strip() == file_id:
                source_files.pop(index)
                deleted_ids.append(file_id)
                removed = True
                break

        if not removed:
            item_errors[file_id] = ['Файл не найден в указанной рубрике.']

    if deleted_ids:
        state.data = state_data
        state.save(update_fields=['data', 'updated_at'])

    return JsonResponse({
        'success': True,
        'state': state.data,
        'processed_count': len(deleted_ids),
        'deleted_ids': deleted_ids,
        'errors': item_errors,
    })


@login_required
@require_POST
@never_cache
def bulk_move_archive_files(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    items, errors = _normalize_archive_file_refs(payload.get('items'))
    target_rubric_id = str(payload.get('target_rubric_id') or '').strip()
    if not target_rubric_id:
        errors.setdefault('target_rubric_id', []).append('Не указана рубрика назначения.')
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    if target_rubric_id in _system_rubric_ids(request.user):
        return JsonResponse({'success': False, 'errors': {'target_rubric_id': ['В системную рубрику «Аукцион» нельзя переместить карточки вручную.']}}, status=400)

    state, state_data, rubrics = _get_archive_state_for_user(request.user)
    rubric_map = {
        str(rubric.get('id') or '').strip(): rubric
        for rubric in rubrics
        if isinstance(rubric, dict)
    }
    target_rubric = rubric_map.get(target_rubric_id)
    if target_rubric is None:
        return JsonResponse({'success': False, 'errors': {'target_rubric_id': ['Рубрика назначения не найдена.']}}, status=404)

    target_files = target_rubric.get('files')
    if not isinstance(target_files, list):
        target_files = []
        target_rubric['files'] = target_files

    moved_ids: list[str] = []
    item_errors: dict[str, list[str]] = {}

    for item in items:
        file_id = item['file_id']
        source_rubric_id = item['source_rubric_id']
        if source_rubric_id == target_rubric_id:
            item_errors[file_id] = ['Файл уже находится в выбранной рубрике.']
            continue

        source_rubric = rubric_map.get(source_rubric_id)
        if source_rubric is None:
            item_errors[file_id] = ['Исходная рубрика не найдена.']
            continue

        source_files = source_rubric.get('files')
        if not isinstance(source_files, list):
            source_files = []
            source_rubric['files'] = source_files

        moved_file = None
        for index, candidate in enumerate(source_files):
            if isinstance(candidate, dict) and str(candidate.get('id') or '').strip() == file_id:
                moved_file = source_files.pop(index)
                break

        if moved_file is None:
            item_errors[file_id] = ['Файл не найден в указанной рубрике.']
            continue

        moved_file['updatedAt'] = int(timezone.now().timestamp() * 1000)
        target_files.insert(0, moved_file)
        moved_ids.append(file_id)

    if moved_ids:
        state.data = state_data
        state.save(update_fields=['data', 'updated_at'])

    return JsonResponse({
        'success': True,
        'state': state.data,
        'processed_count': len(moved_ids),
        'moved_ids': moved_ids,
        'target_rubric_id': target_rubric_id,
        'errors': item_errors,
    })


@require_GET
def reviews_api(request: HttpRequest) -> JsonResponse:
    items = []
    review_qs = Review.objects.select_related('user')
    # Hidden reviews are visible only to a superuser (moderation); regular
    # visitors never see them.
    if not request.user.is_superuser:
        review_qs = review_qs.filter(is_hidden=False)
    for review in review_qs.all()[:200]:
        items.append({
            'id': review.id,
            'rating': review.rating,
            'text': review.text,
            'author': review.user.get_username(),
            'created_at': review.created_at.isoformat(),
            'updated_at': review.updated_at.isoformat(),
            'is_owner': bool(request.user.is_authenticated and review.user_id == request.user.id),
            'is_hidden': review.is_hidden,
        })
    return JsonResponse({'success': True, 'reviews': items})


@login_required
@require_POST
def reviews_create_api(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    rating = int(payload.get('rating') or 0)
    text = str(payload.get('text') or '').strip()
    if rating < 1 or rating > 5:
        return JsonResponse({'success': False, 'errors': {'rating': ['Рейтинг должен быть от 1 до 5']}}, status=400)
    if not text:
        return JsonResponse({'success': False, 'errors': {'text': ['Текст отзыва не может быть пустым']}}, status=400)
    review = Review.objects.create(user=request.user, rating=rating, text=text)
    return JsonResponse({'success': True, 'id': review.id})


@login_required
@require_http_methods(["PATCH"])
def reviews_update_api(request: HttpRequest, review_id: int) -> JsonResponse:
    review = Review.objects.filter(id=review_id, user=request.user).first()
    if not review:
        return JsonResponse({'success': False, 'errors': {'review': ['Отзыв не найден']}}, status=404)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    if 'rating' in payload:
        rating = int(payload.get('rating') or 0)
        if rating < 1 or rating > 5:
            return JsonResponse({'success': False, 'errors': {'rating': ['Рейтинг должен быть от 1 до 5']}}, status=400)
        review.rating = rating
    if 'text' in payload:
        text = str(payload.get('text') or '').strip()
        if not text:
            return JsonResponse({'success': False, 'errors': {'text': ['Текст отзыва не может быть пустым']}}, status=400)
        review.text = text
    review.save(update_fields=['rating', 'text', 'updated_at'])
    return JsonResponse({'success': True})


@login_required
@require_POST
def accept_terms(request: HttpRequest) -> JsonResponse:
    profile, _ = Profile.objects.get_or_create(user=request.user)
    profile.mark_terms_accepted(ip=request.META.get('REMOTE_ADDR'))
    logger.info(messages.TERMS_ACCEPTED_LOG, request.user.pk, django_settings.TERMS_VERSION)
    return JsonResponse({'success': True, 'message': messages.TERMS_ACCEPTED_TOAST})
