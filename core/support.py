"""Website support: public intake, staff-only inbox and SMTP replies."""
import logging
import uuid
from datetime import timedelta
from functools import wraps
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_GET
from .models import SupportTicket, SupportReply

logger = logging.getLogger(__name__)


class TicketForm(forms.Form):
    email = forms.EmailField(label='Email', max_length=254)
    name = forms.CharField(label='Как к Вам обращаться', max_length=120)
    question = forms.CharField(label='Ваш вопрос', max_length=10000, widget=forms.Textarea(attrs={'rows': 6}))
    submission_id = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class ReplyForm(forms.Form):
    text = forms.CharField(label='Ответ пользователю', max_length=20000, widget=forms.Textarea(attrs={'rows': 8}))
    request_id = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


def sender_key(request):
    ip = request.META.get('HTTP_X_REAL_IP') if settings.SKLAD_TRUST_PROXY_IP else None
    return salted_hmac('support-ip', ip or request.META.get('REMOTE_ADDR', '')).hexdigest()


class StaffAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError('Доступ только для сотрудников.')


class SupportLogin(LoginView):
    template_name = 'support/login.html'
    authentication_form = StaffAuthenticationForm

    def post(self, request, *args, **kwargs):
        key = 'support-login-' + sender_key(request)
        cache.add(key, 0, 300)
        if cache.incr(key) > 10:
            return HttpResponse('Слишком много попыток. Повторите через 5 минут.', status=429)
        return super().post(request, *args, **kwargs)


class SupportLogout(LogoutView):
    http_method_names = ['post', 'options']
    next_page = '/support/login'


def staff(view):
    @wraps(view)
    @login_required
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_active or not request.user.is_staff:
            return HttpResponseForbidden('Доступ только для сотрудников.')
        return view(request, *args, **kwargs)
    return wrapped


def send_support_mail(subject, body, recipient, reply_to=None):
    if not settings.DEFAULT_FROM_EMAIL or not recipient:
        raise RuntimeError('Support email is not configured')
    if settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend' and not settings.EMAIL_HOST:
        raise RuntimeError('SMTP is not configured')
    message = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient], reply_to=reply_to or [])
    if message.send(fail_silently=False) != 1:
        raise RuntimeError('Mail backend did not accept the message')


def notify_ticket(pk):
    # Kept for compatibility with old scheduled jobs. Intake never sends mail.
    return


@require_POST
def submit(request):
    if int(request.META.get('CONTENT_LENGTH') or 0) > 64000:
        return JsonResponse({'error': 'Слишком большой запрос.'}, status=413)
    form = TicketForm(request.POST)
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if not form.is_valid():
        if ajax:
            return JsonResponse({'errors': form.errors.get_json_data()}, status=400)
        return render(request, 'support/public.html', {'form': form}, status=400)
    token = form.cleaned_data['submission_id']
    ticket = SupportTicket.objects.filter(submission_id=token).first()
    if ticket is None:
        fingerprint = sender_key(request)
        if SupportTicket.objects.filter(sender_hash=fingerprint, created_at__gte=timezone.now()-timedelta(minutes=15)).count() >= 5:
            return JsonResponse({'error': 'Слишком много сообщений. Повторите через 15 минут.'}, status=429)
        ticket, _ = SupportTicket.objects.get_or_create(submission_id=token, defaults={
            'email': form.cleaned_data['email'], 'name': form.cleaned_data['name'],
            'question': form.cleaned_data['question'], 'sender_hash': fingerprint})
    if ajax:
        return JsonResponse({'message': 'Сообщение отправлено'})
    return render(request, 'support/public.html', {'sent': True})


@staff
@require_GET
def inbox(request):
    status = request.GET.get('status', '')
    query = request.GET.get('q', '').strip()[:200]
    tickets = SupportTicket.objects.all()
    if status in SupportTicket.Status.values:
        tickets = tickets.filter(status=status)
    if query:
        match = Q(email__icontains=query) | Q(question__icontains=query)
        identifier = query.lstrip('#')
        if identifier.isdecimal() and len(identifier) < 19:
            match |= Q(pk=int(identifier))
        tickets = tickets.filter(match)
    counts = dict(SupportTicket.objects.values('status').annotate(total=Count('pk')).values_list('status', 'total'))
    return render(request, 'support/inbox.html', {
        'page': Paginator(tickets, 30).get_page(request.GET.get('page')),
        'filters': [(key, label, counts.get(key, 0)) for key, label in SupportTicket.Status.choices],
        'total': sum(counts.values()), 'status': status, 'query': query,
    })


@staff
@require_GET
def detail(request, pk):
    ticket = get_object_or_404(SupportTicket.objects.prefetch_related('replies'), pk=pk)
    template = 'support/detail_content.html' if request.GET.get('modal') == '1' else 'support/detail.html'
    return render(request, template, {'ticket': ticket, 'reply_form': ReplyForm()})


@staff
@require_POST
def work(request, pk):
    with transaction.atomic():
        ticket = get_object_or_404(SupportTicket.objects.select_for_update(), pk=pk)
        ticket.status = SupportTicket.Status.WORK
        ticket.save(update_fields=['status'])
    return redirect('support:detail', pk=pk)


@staff
@require_POST
def reply(request, pk):
    form = ReplyForm(request.POST)
    ticket = get_object_or_404(SupportTicket, pk=pk)
    if form.is_valid():
        try:
            with transaction.atomic():
                ticket = SupportTicket.objects.select_for_update().get(pk=pk)
                existing = SupportReply.objects.filter(request_id=form.cleaned_data['request_id']).first()
                if existing and existing.ticket_id != pk:
                    form.add_error(None, 'Недопустимый идентификатор ответа.')
                elif not existing:
                    text = form.cleaned_data['text']
                    send_support_mail(f'СКлад — ответ на обращение #{ticket.pk}',
                        f'Здравствуйте, {ticket.name}!\n\n{text}\n\nТехподдержка СКлад\nОбращение #{ticket.pk}',
                        ticket.email)
                    SupportReply.objects.create(ticket=ticket, text=text, sent_at=timezone.now(), request_id=form.cleaned_data['request_id'])
                    ticket.status = SupportTicket.Status.ANSWERED
                    ticket.save(update_fields=['status'])
        except Exception:
            logger.warning('Support reply failed for ticket %s', pk)
            form.add_error(None, 'Не удалось отправить ответ. Текст сохранён в форме. Проверьте почтовые настройки и повторите.')
        if not form.errors:
            return redirect(reverse('support:detail', args=[pk]) + '?sent=1')
    return render(request, 'support/detail.html', {'ticket': ticket, 'reply_form': form}, status=400)


urlpatterns = [
    path('', inbox, name='inbox'), path('login', SupportLogin.as_view(), name='login'),
    path('logout', SupportLogout.as_view(), name='logout'), path('submit', submit, name='submit'),
    path('tickets/<int:pk>', detail, name='detail'), path('tickets/<int:pk>/work', work, name='work'),
    path('tickets/<int:pk>/reply', reply, name='reply'),
]
