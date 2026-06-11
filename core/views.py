"""Replaces the Java Spring MVC controllers with Django view functions."""
from __future__ import annotations

import json
import logging

from django.db import transaction

from django.conf import settings as django_settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core import messages
from .forms import ArchiveFileForm, LoginForm, RegistrationForm, RubricForm
from .models import ArchiveFile, ArchiveState, Profile, Review, Rubric

logger = logging.getLogger("core.moderation")


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
def profile(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'profile.html',
        _seo_context(
            request,
            title='Профиль - СКлад',
            description='Личный профиль пользователя сервиса СКлад.',
            indexable=False,
            canonical_path=reverse('core:profile'),
        ),
    )


@ensure_csrf_cookie
def settings(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'settings.html',
        _seo_context(
            request,
            title='Настройки - СКлад',
            description='Персональные настройки интерфейса и приватности пользователя.',
            indexable=False,
            canonical_path=reverse('core:settings'),
        ),
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


@ensure_csrf_cookie
def news(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'news.html',
        _seo_context(
            request,
            title='Инструкции и новости проекта - СКлад',
            description='Инструкции по использованию СКлада, новости проекта, обновления функциональности и полезная информация о сервисе.',
            indexable=True,
            canonical_path=reverse('core:news'),
        ),
    )


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
        username_available = not User.objects.filter(username__iexact=username).exists()

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
    return JsonResponse({'success': True})


@require_POST
def login_user(request: HttpRequest) -> JsonResponse:
    form = LoginForm(request, data=request.POST)
    if form.is_valid():
        login(request, form.get_user())
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'errors': form.errors}, status=400)


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
            },
        })

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    request.user.first_name = str(payload.get('first', request.user.first_name) or '')[:150]
    request.user.last_name = str(payload.get('last', request.user.last_name) or '')[:150]
    request.user.email = str(payload.get('email', request.user.email) or '')[:254]
    profile.link = str(payload.get('link', profile.link) or '')[:255]
    profile.privacy_level = str(payload.get('privacy_level', profile.privacy_level) or 'public')[:50]

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

    request.user.save(update_fields=['first_name', 'last_name', 'email'])
    profile.save(update_fields=['link', 'privacy_level', 'avatar_meta'])
    return JsonResponse({'success': True})


@login_required
@require_http_methods(["GET", "PUT"])
@never_cache
def archive_state_api(request: HttpRequest) -> JsonResponse:
    state, _ = ArchiveState.objects.get_or_create(user=request.user, defaults={'data': {'rubrics': []}})
    if request.method == 'GET':
        return JsonResponse({'success': True, 'state': state.data if isinstance(state.data, dict) else {'rubrics': []}})

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'success': False, 'errors': {'state': ['Некорректный JSON']}}, status=400)

    state_payload = payload.get('state', payload)
    if not isinstance(state_payload, dict):
        return JsonResponse({'success': False, 'errors': {'state': ['Ожидается объект состояния']}}, status=400)

    state.data = state_payload
    state.save(update_fields=['data', 'updated_at'])
    return JsonResponse({'success': True})


@login_required
@require_GET
@never_cache
def list_rubrics(request: HttpRequest) -> JsonResponse:
    profile, _ = Profile.objects.get_or_create(user=request.user)
    rubrics = list(Rubric.objects.filter(profile=profile).values('id', 'name', 'slug', 'is_text_mode', 'field_schema'))
    return JsonResponse({'success': True, 'rubrics': rubrics})


@login_required
@require_GET
@never_cache
def list_rubric_files(request: HttpRequest, rubric_id: int) -> JsonResponse:
    files = list(
        ArchiveFile.objects.filter(rubric_id=rubric_id, owner=request.user).values('id', 'rubric_id', 'title', 'data', 'created_at', 'updated_at')
    )
    return JsonResponse({'success': True, 'files': files})


@login_required
@require_POST
@never_cache
def create_rubric(request: HttpRequest) -> JsonResponse:
    form = RubricForm(request.POST)
    if form.is_valid():
        rubric = form.save(commit=False)
        profile, _ = Profile.objects.get_or_create(user=request.user)
        rubric.profile = profile
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

        if archive_file.content_hash:
            duplicate_hash = (
                ArchiveFile.objects.filter(owner=request.user, content_hash=archive_file.content_hash)
                .exclude(pk=archive_file.pk)
                .first()
            )
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
    for review in Review.objects.select_related('user').all()[:200]:
        items.append({
            'id': review.id,
            'rating': review.rating,
            'text': review.text,
            'author': review.user.get_username(),
            'created_at': review.created_at.isoformat(),
            'updated_at': review.updated_at.isoformat(),
            'is_owner': bool(request.user.is_authenticated and review.user_id == request.user.id),
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
