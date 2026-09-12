import uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, Client, override_settings
from core.models import SupportTicket, SupportReply
from core.support import notify_ticket


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   DEFAULT_FROM_EMAIL='support@example.com', SUPPORT_EMAIL='team@example.com',
                   SESSION_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=False)
class SupportTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('operator', password='Test-only-password-123', is_staff=True)
        self.data = {'email': 'person@example.com', 'name': 'Анна', 'question': 'Как перенести архив?', 'submission_id': str(uuid.uuid4())}

    def create(self):
        response = self.client.post('/support/submit', self.data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        return SupportTicket.objects.get()

    def test_public_create_email_and_idempotency(self):
        ticket = self.create()
        self.assertEqual(ticket.status, 'new')
        self.assertEqual(ticket.source, 'website')
        self.assertIsNone(ticket.notification_sent_at)
        self.create()
        self.assertEqual(len(mail.outbox), 0)

    def test_required_fields_and_csrf(self):
        for field in ('email', 'name', 'question'):
            data = {**self.data, field: ' '}
            self.assertEqual(self.client.post('/support/submit', data).status_code, 400)
        self.assertEqual(SupportTicket.objects.count(), 0)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/support/submit', self.data).status_code, 403)
        client.get('/')
        self.assertEqual(client.post('/support/submit', {**self.data, 'csrfmiddlewaretoken': client.cookies['csrftoken'].value}).status_code, 200)

    def test_access_protection(self):
        ticket = self.create()
        for url in ('/support', f'/support/tickets/{ticket.pk}'):
            self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post(f'/support/tickets/{ticket.pk}/work').status_code, 302)
        user = get_user_model().objects.create_user('ordinary', password='test')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/support').status_code, 403)
        self.assertEqual(self.client.post(f'/support/tickets/{ticket.pk}/reply', {'text': 'oops'}).status_code, 403)

    def test_staff_search_filter_details_and_work(self):
        ticket = self.create()
        self.client.force_login(self.staff)
        for query in ('person@', str(ticket.pk), 'перенести'):
            self.assertContains(self.client.get('/support', {'q': query}), 'Анна')
        self.assertNotContains(self.client.get('/support', {'status': 'answered'}), 'person@example.com')
        self.assertContains(self.client.get(f'/support/tickets/{ticket.pk}?modal=1'), 'Как перенести архив?')
        self.assertEqual(self.client.get(f'/support/tickets/{ticket.pk}/work').status_code, 405)
        self.client.post(f'/support/tickets/{ticket.pk}/work')
        ticket.refresh_from_db(); self.assertEqual(ticket.status, 'work')

    def test_reply_success_failure_and_duplicate(self):
        ticket = self.create(); self.client.force_login(self.staff)
        url = f'/support/tickets/{ticket.pk}/reply'
        data = {'text': 'Откройте меню экспорта.', 'request_id': str(uuid.uuid4())}
        with patch('core.support.send_support_mail', side_effect=OSError('SMTP failure')):
            self.assertEqual(self.client.post(url, data).status_code, 400)
        ticket.refresh_from_db(); self.assertEqual(ticket.status, 'new')
        self.assertFalse(SupportReply.objects.exists())
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        ticket.refresh_from_db(); self.assertEqual(ticket.status, 'answered')
        self.assertEqual(SupportReply.objects.count(), 1)
        self.assertEqual(mail.outbox[-1].to, ['person@example.com'])
        self.assertEqual(len(mail.outbox), 1)

    def test_notification_failure_keeps_ticket_and_retry(self):
        with patch('core.support.send_support_mail', side_effect=OSError('SMTP failure')):
            ticket = self.create()
        self.assertIsNone(ticket.notification_sent_at)
        notify_ticket(ticket.pk)
        ticket.refresh_from_db(); self.assertIsNone(ticket.notification_sent_at)
        self.assertEqual(len(mail.outbox), 0)

    def test_escape_and_rate_limit(self):
        self.data['question'] = '<script>alert(1)</script>'
        ticket = self.create(); self.client.force_login(self.staff)
        response = self.client.get(f'/support/tickets/{ticket.pk}')
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        for _ in range(4):
            self.client.post('/support/submit', {**self.data, 'submission_id': str(uuid.uuid4())})
        self.assertEqual(self.client.post('/support/submit', {**self.data, 'submission_id': str(uuid.uuid4())}).status_code, 429)

    def test_sort_pagination_and_logout(self):
        SupportTicket.objects.bulk_create([SupportTicket(email='sort@example.com', name=str(i), question='Тест', sender_hash='test') for i in range(35)])
        self.client.force_login(self.staff)
        page = self.client.get('/support').context['page']
        self.assertEqual(len(page), 30)
        self.assertGreater(page[0].pk, page[-1].pk)
        self.assertEqual(len(self.client.get('/support', {'page': 2}).context['page']), 5)
        self.assertEqual(self.client.get('/support/logout').status_code, 405)
        self.client.post('/support/logout')
        self.assertEqual(self.client.get('/support').status_code, 302)
