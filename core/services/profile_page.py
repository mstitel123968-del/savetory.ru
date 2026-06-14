"""Data preparation for the extended public/user profile page."""
from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Prefetch
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from core.models import ArchiveFile, ArchiveFileImage, ArchiveState, Friendship, Profile, Rubric
from core.services.friendships import get_friends, get_relationship_status


PROFILE_BACKGROUND_COVERS = [
    {
        'id': 'cover-mountain-sunrise.png',
        'file': 'img/profile-covers/cover-mountain-sunrise.png',
        'name': 'Горное озеро',
        'legacy_ids': ['ChatGPT Image 13 июн. 2026 г., 23_37_14 (1).png'],
    },
    {
        'id': 'cover-misty-forest.png',
        'file': 'img/profile-covers/cover-misty-forest.png',
        'name': 'Туманный лес',
        'legacy_ids': ['ChatGPT Image 13 июн. 2026 г., 23_37_14 (2).png'],
    },
    {
        'id': 'cover-sea-sunset.png',
        'file': 'img/profile-covers/cover-sea-sunset.png',
        'name': 'Морской закат',
        'legacy_ids': ['ChatGPT Image 13 июн. 2026 г., 23_37_15 (3).png'],
    },
    {
        'id': 'cover-aurora-lake.png',
        'file': 'img/profile-covers/cover-aurora-lake.png',
        'name': 'Северное сияние',
        'legacy_ids': ['ChatGPT Image 13 июн. 2026 г., 23_37_16 (4).png'],
    },
]


def get_available_profile_backgrounds() -> list[dict]:
    """Return built-in selectable profile backgrounds from static assets."""

    items = []
    for cover in PROFILE_BACKGROUND_COVERS:
        items.append({
            'id': cover['id'],
            'path': cover['file'],
            'url': static(cover['file']),
            'name': cover['name'],
        })
    return items


def validate_profile_background(value: str) -> str:
    """Return a safe selectable background id or an empty string."""

    raw = str(value or '').strip().replace('\\', '/')
    if not raw:
        return ''
    allowed = {}
    for cover in PROFILE_BACKGROUND_COVERS:
        allowed[cover['id']] = cover['id']
        allowed[cover['file']] = cover['id']
        allowed[f"profile-covers/{cover['id']}"] = cover['id']
        for legacy in cover.get('legacy_ids', []):
            allowed[legacy] = cover['id']
    if raw not in allowed:
        raise ValueError('Profile background is not in the allowed list.')
    return allowed[raw]


def _display_name(user, profile: Profile | None = None) -> str:
    if profile and profile.display_name:
        return profile.display_name
    full_name = user.get_full_name().strip()
    return full_name or user.get_username()


def _presence(profile: Profile | None) -> dict:
    last_seen = profile.last_seen_at if profile else None
    if not last_seen:
        return {'is_online': False, 'label': 'Активность неизвестна', 'last_seen_at': None}
    local_seen = timezone.localtime(last_seen)
    now = timezone.localtime(timezone.now())
    if now - local_seen <= timedelta(minutes=5):
        label = 'Онлайн'
        is_online = True
    elif local_seen.date() == now.date():
        label = f"Заходил сегодня в {local_seen:%H:%M}"
        is_online = False
    elif local_seen.date() == (now - timedelta(days=1)).date():
        label = f"Заходил вчера в {local_seen:%H:%M}"
        is_online = False
    else:
        label = f"Заходил {local_seen:%d.%m.%Y} в {local_seen:%H:%M}"
        is_online = False
    return {'is_online': is_online, 'label': label, 'last_seen_at': last_seen.isoformat()}


def _is_friend(viewer, user) -> bool:
    if not viewer.is_authenticated or viewer.pk == user.pk:
        return False
    return get_relationship_status(viewer, user)['status'] == Friendship.Status.ACCEPTED


def _can_view_details(viewer, user, profile: Profile | None) -> bool:
    if viewer.is_authenticated and (viewer.pk == user.pk or viewer.is_superuser):
        return True
    privacy = (profile.privacy_level if profile else 'public') or 'public'
    if privacy == 'public':
        return True
    if privacy == 'friends':
        return _is_friend(viewer, user)
    return False


def _background_payload(profile: Profile | None) -> dict | None:
    if not profile or not profile.background_image:
        return None
    try:
        relative = validate_profile_background(profile.background_image)
    except ValueError:
        return None
    if not relative:
        return None
    background = next((item for item in get_available_profile_backgrounds() if item['id'] == relative), None)
    if not background:
        return None
    return {
        'id': relative,
        'path': background['path'],
        'url': background['url'],
    }


def _image_url(image: ArchiveFileImage | None) -> str:
    if not image or not image.image:
        return ''
    try:
        return image.image.url
    except ValueError:
        return ''


def _public_collection_url(user, rubric: Rubric) -> str:
    slug = rubric.public_slug or rubric.slug
    return reverse('core:public-collection', kwargs={'username': user.get_username(), 'rubric_slug': slug})


def _state_public_collection_url(user, rubric: dict) -> str:
    slug = str(rubric.get('publicSlug') or rubric.get('slug') or rubric.get('id') or '').strip()
    return reverse('core:public-collection', kwargs={'username': user.get_username(), 'rubric_slug': slug})


def _state_image_src(value) -> str:
    if not isinstance(value, dict):
        return ''
    items = value.get('items')
    if not isinstance(items, list) or not items:
        return ''
    pinned_id = str(value.get('pinnedId') or '')
    primary = None
    if pinned_id:
        primary = next((item for item in items if isinstance(item, dict) and str(item.get('id') or '') == pinned_id), None)
    if primary is None:
        primary = next((item for item in items if isinstance(item, dict)), None)
    return str((primary or {}).get('src') or '')


def _state_file_title(rubric: dict, file_item: dict) -> str:
    values = file_item.get('values') if isinstance(file_item.get('values'), dict) else {}
    title = str(values.get('title') or file_item.get('title') or '').strip()
    return title or str(rubric.get('name') or '')


def _state_file_thumb(rubric: dict, file_item: dict) -> str:
    fields = rubric.get('fields') if isinstance(rubric.get('fields'), list) else []
    values = file_item.get('values') if isinstance(file_item.get('values'), dict) else {}
    image_fields = [field for field in fields if isinstance(field, dict) and field.get('type') == 'image']
    image_fields.sort(key=lambda field: 0 if field.get('id') == 'photo' else 1)
    for field in image_fields:
        src = _state_image_src(values.get(field.get('id')))
        if src:
            return src
    return ''


def _state_dt(value) -> timezone.datetime:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0
    if number > 10_000_000_000:
        number /= 1000
    if number <= 0:
        return timezone.now()
    return datetime.fromtimestamp(number, tz=timezone.get_current_timezone())


def _archive_state_payload(user, *, is_owner: bool) -> dict | None:
    state = ArchiveState.objects.filter(user=user).first()
    state_data = state.data if state and isinstance(state.data, dict) else {}
    rubrics = state_data.get('rubrics') if isinstance(state_data.get('rubrics'), list) else []
    if not rubrics:
        return None

    visible_rubrics = [
        rubric for rubric in rubrics
        if isinstance(rubric, dict) and (is_owner or bool(rubric.get('publicEnabled')))
    ]
    rubric_items = []
    record_items = []
    records_count = 0
    for rubric in visible_rubrics:
        files = rubric.get('files') if isinstance(rubric.get('files'), list) else []
        records_count += len(files)
        cover = ''
        for file_item in files:
            if isinstance(file_item, dict):
                cover = _state_file_thumb(rubric, file_item)
                if cover:
                    break
        rubric_url = reverse('core:archive') if is_owner else _state_public_collection_url(user, rubric)
        rubric_items.append({
            'id': str(rubric.get('id') or ''),
            'name': str(rubric.get('name') or ''),
            'description': str(rubric.get('description') or ''),
            'records_count': len(files),
            'cover_url': cover,
            'icon': 'folder',
            'updated_at': _state_dt(rubric.get('updatedAt') or rubric.get('createdAt')).isoformat(),
            'url': rubric_url,
        })
        for file_item in files:
            if not isinstance(file_item, dict):
                continue
            created = _state_dt(file_item.get('createdAt'))
            record_items.append({
                'id': str(file_item.get('id') or ''),
                'title': _state_file_title(rubric, file_item),
                'rubric': str(rubric.get('name') or ''),
                'is_public': bool(rubric.get('publicEnabled')) or is_owner,
                'thumbnail_url': _state_file_thumb(rubric, file_item),
                'created_at': created.isoformat(),
                'created_at_label': timezone.localtime(created).strftime('%d.%m.%Y'),
                'url': rubric_url,
            })
    rubric_items.sort(key=lambda item: item['updated_at'], reverse=True)
    record_items.sort(key=lambda item: item['created_at'], reverse=True)
    return {
        'rubrics_count': len(visible_rubrics),
        'records_count': records_count,
        'rubrics': rubric_items[:8],
        'records': record_items[:4],
    }


def _relationship_payload(viewer, user) -> dict:
    if not viewer.is_authenticated or viewer.pk == user.pk:
        return {'status': 'self' if viewer.is_authenticated and viewer.pk == user.pk else 'none', 'requester_id': None}
    status = get_relationship_status(viewer, user)
    return {
        'status': status['status'],
        'requester_id': status['requester_id'],
    }


def _basic_profile_payload(user, profile: Profile | None, *, can_view_details: bool) -> dict:
    meta = profile.avatar_meta if profile and isinstance(profile.avatar_meta, dict) else {}
    link = profile.link if profile and can_view_details else ''
    return {
        'id': user.pk,
        'username': user.get_username(),
        'first_name': user.first_name if can_view_details else '',
        'last_name': user.last_name if can_view_details else '',
        'display_name': _display_name(user, profile),
        'avatar_data': meta.get('avatar_data', '') if profile else '',
        'avatar_pos': meta.get('avatar_pos', {'x': 50, 'y': 50, 'scale': 100}) if profile else {'x': 50, 'y': 50, 'scale': 100},
        'background': _background_payload(profile),
        'city': meta.get('city', '') if can_view_details else '',
        'bio': profile.bio if profile and can_view_details else '',
        'interests': meta.get('interests', '') if can_view_details else '',
        'link': link if link.startswith(('http://', 'https://')) else '',
        'date_joined': user.date_joined.isoformat() if user.date_joined else None,
        'date_joined_label': timezone.localtime(user.date_joined).strftime('%d.%m.%Y') if user.date_joined else '',
        'presence': _presence(profile) if can_view_details else {'is_online': False, 'label': '', 'last_seen_at': None},
    }


def _visible_rubrics(user, viewer, profile: Profile, can_view_details: bool):
    queryset = Rubric.objects.filter(profile=profile)
    if not (viewer.is_authenticated and (viewer.pk == user.pk or viewer.is_superuser)):
        queryset = queryset.filter(is_public=True)
    return queryset.annotate(
        file_count=Count('files', distinct=True),
        last_file_updated_at=Max('files__updated_at'),
    )


def _public_rubrics_payload(user, rubrics) -> list[dict]:
    image_prefetch = Prefetch('files__images', queryset=ArchiveFileImage.objects.order_by('display_order', 'id'))
    rubrics = list(rubrics.prefetch_related(image_prefetch).order_by('-updated_at', '-created_at')[:8])
    items = []
    for rubric in rubrics:
        cover = ''
        for archive_file in list(rubric.files.all()):
            cover = _image_url(next(iter(archive_file.images.all()), None))
            if cover:
                break
        items.append({
            'id': rubric.pk,
            'name': rubric.name,
            'description': '',
            'records_count': rubric.file_count,
            'cover_url': cover,
            'icon': 'folder',
            'updated_at': (rubric.last_file_updated_at or rubric.updated_at or rubric.created_at).isoformat(),
            'url': _public_collection_url(user, rubric) if rubric.is_public else '',
        })
    return items


def _latest_records_payload(user, visible_rubrics) -> list[dict]:
    rubric_ids = list(visible_rubrics.values_list('id', flat=True))
    if not rubric_ids:
        return []
    files = (
        ArchiveFile.objects.filter(rubric_id__in=rubric_ids)
        .select_related('rubric')
        .prefetch_related(Prefetch('images', queryset=ArchiveFileImage.objects.order_by('display_order', 'id')))
        .order_by('-created_at', '-id')[:4]
    )
    items = []
    for archive_file in files:
        image = next(iter(archive_file.images.all()), None)
        collection_url = _public_collection_url(user, archive_file.rubric) if archive_file.rubric.is_public else ''
        items.append({
            'id': archive_file.pk,
            'title': archive_file.title,
            'rubric': archive_file.rubric.name,
            'is_public': archive_file.rubric.is_public,
            'thumbnail_url': _image_url(image),
            'created_at': archive_file.created_at.isoformat(),
            'created_at_label': timezone.localtime(archive_file.created_at).strftime('%d.%m.%Y'),
            'url': f"{collection_url}#card-{archive_file.pk}" if collection_url else '',
        })
    return items


def _friends_payload(user, viewer) -> dict:
    friends_queryset = get_friends(user).filter(is_active=True).select_related('profile')
    can_view_private_friends = viewer.is_authenticated and (viewer.pk == user.pk or viewer.is_superuser)
    if not can_view_private_friends:
        friends_queryset = friends_queryset.exclude(profile__privacy_level='private')
    visible_friends = list(friends_queryset[:5])
    total = friends_queryset.count()
    viewer_friends = set()
    if viewer.is_authenticated and viewer.pk != user.pk:
        viewer_friends = set(get_friends(viewer).values_list('id', flat=True))
    items = []
    for friend in visible_friends:
        profile = getattr(friend, 'profile', None)
        meta = profile.avatar_meta if profile and isinstance(profile.avatar_meta, dict) else {}
        items.append({
            'id': friend.pk,
            'display_name': _display_name(friend, profile),
            'avatar_data': meta.get('avatar_data', '') if profile else '',
            'url': reverse('core:community-user-profile', kwargs={'username': friend.get_username()}),
            'is_mutual': friend.pk in viewer_friends,
        })
    return {
        'total': total,
        'mutual_count': friends_queryset.filter(id__in=viewer_friends).count() if viewer_friends else 0,
        'items': items,
    }


def _activity_payload(user, profile: Profile | None, visible_rubrics, latest_records) -> list[dict]:
    items = []
    for rubric in visible_rubrics.order_by('-created_at')[:4]:
        if rubric.is_public:
            items.append({
                'type': 'rubric_created',
                'label': f"Создана публичная рубрика «{rubric.name}»",
                'created_at': rubric.created_at,
                'url': _public_collection_url(user, rubric),
            })
        if rubric.is_public and rubric.updated_at and rubric.updated_at != rubric.created_at:
            items.append({
                'type': 'rubric_updated',
                'label': f"Обновлена публичная рубрика «{rubric.name}»",
                'created_at': rubric.updated_at,
                'url': _public_collection_url(user, rubric),
            })
    for record in latest_records:
        if not record.get('is_public') or not record.get('url'):
            continue
        items.append({
            'type': 'record_created',
            'label': f"Добавлена запись «{record['title']}»",
            'created_at': datetime.fromisoformat(record['created_at']),
            'url': record['url'],
        })
    if profile and profile.updated_at:
        items.append({
            'type': 'profile_updated',
            'label': 'Обновлены публичные данные профиля',
            'created_at': profile.updated_at,
            'url': reverse('core:community-user-profile', kwargs={'username': user.get_username()}),
        })
    items.sort(key=lambda item: item['created_at'], reverse=True)
    return [
        {
            **item,
            'created_at': item['created_at'].isoformat(),
            'created_at_label': timezone.localtime(item['created_at']).strftime('%d.%m.%Y %H:%M'),
        }
        for item in items[:8]
    ]


def build_extended_profile_context(viewer, username: str) -> dict:
    """Build privacy-filtered data for an extended profile page."""

    User = get_user_model()
    user = User.objects.select_related('profile').filter(username__iexact=username).first()
    if not user or (not user.is_active and not (viewer.is_authenticated and viewer.is_superuser)):
        return {'found': False}

    profile = getattr(user, 'profile', None)
    if profile is None:
        profile = Profile(user=user)

    can_view_details = _can_view_details(viewer, user, profile)
    relationship = _relationship_payload(viewer, user)
    privacy = (profile.privacy_level if profile else 'public') or 'public'
    is_owner = viewer.is_authenticated and viewer.pk == user.pk
    is_closed = privacy == 'private' and not can_view_details

    basic = _basic_profile_payload(user, profile, can_view_details=can_view_details or is_closed)
    if is_closed:
        basic.update({
            'city': '',
            'bio': '',
            'interests': '',
            'link': '',
            'presence': {'is_online': False, 'label': '', 'last_seen_at': None},
        })
        return {
            'found': True,
            'is_closed': True,
            'is_owner': is_owner,
            'can_view_details': False,
            'profile': basic,
            'relationship': relationship,
            'message': 'Профиль закрыт',
            'actions': _actions_payload(viewer, user, relationship),
        }

    visible_rubrics = _visible_rubrics(user, viewer, profile, can_view_details)
    public_rubrics_queryset = visible_rubrics if is_owner else visible_rubrics.filter(is_public=True)
    archive_state = _archive_state_payload(user, is_owner=is_owner)
    latest_records = archive_state['records'] if archive_state else _latest_records_payload(user, visible_rubrics)
    public_rubrics = archive_state['rubrics'] if archive_state else _public_rubrics_payload(user, public_rubrics_queryset)
    friends = _friends_payload(user, viewer) if can_view_details else {'total': 0, 'mutual_count': 0, 'items': []}
    rubrics_count = archive_state['rubrics_count'] if archive_state else visible_rubrics.count()
    records_count = archive_state['records_count'] if archive_state else ArchiveFile.objects.filter(rubric_id__in=visible_rubrics.values('id')).count()

    return {
        'found': True,
        'is_closed': False,
        'is_owner': is_owner,
        'can_view_details': can_view_details,
        'profile': basic,
        'relationship': relationship,
        'stats': {
            'rubrics_count': rubrics_count,
            'public_rubrics_count': rubrics_count if archive_state else public_rubrics_queryset.count(),
            'records_count': records_count,
            'friends_count': friends['total'],
            'date_joined': basic['date_joined'],
            'date_joined_label': basic['date_joined_label'],
        },
        'public_rubrics': public_rubrics,
        'latest_records': latest_records,
        'friends': friends,
        'activity': _activity_payload(user, profile, visible_rubrics, latest_records),
        'actions': _actions_payload(viewer, user, relationship),
        'available_backgrounds': get_available_profile_backgrounds() if is_owner else [],
    }


def _actions_payload(viewer, user, relationship: dict) -> dict:
    is_owner = viewer.is_authenticated and viewer.pk == user.pk
    status = relationship.get('status')
    requester_id = relationship.get('requester_id')
    return {
        'can_edit_profile': is_owner,
        'can_open_profile_settings': is_owner,
        'can_add_friend': viewer.is_authenticated and not is_owner and status == 'none',
        'friend_request_sent': viewer.is_authenticated and not is_owner and status == Friendship.Status.PENDING and requester_id == viewer.pk,
        'can_accept_friend_request': viewer.is_authenticated and not is_owner and status == Friendship.Status.PENDING and requester_id == user.pk,
        'can_remove_friend': viewer.is_authenticated and not is_owner and status == Friendship.Status.ACCEPTED,
        'can_message': viewer.is_authenticated and not is_owner and status == Friendship.Status.ACCEPTED,
        'message_url': reverse('core:message-dialog', kwargs={'user_id': user.pk}) if viewer.is_authenticated and not is_owner and status == Friendship.Status.ACCEPTED else '',
    }
