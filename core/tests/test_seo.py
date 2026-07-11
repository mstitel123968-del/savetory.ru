from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class SeoPagesTests(TestCase):
    def test_landing_has_required_seo_and_visible_copy(self):
        response = self.client.get(reverse('core:landing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<title>СКлад — сервис коллекционера для хранения и учёта коллекций</title>', html=True)
        self.assertContains(response, '<h1 class="landing-seo-title">СКлад — сервис коллекционера</h1>', html=True)
        self.assertContains(response, 'Храните информацию о коллекционных предметах в одном месте.')
        self.assertEqual(response.content.count(b'<h1'), 1)
        self.assertContains(response, 'property="og:title"')
        self.assertContains(response, 'rel="canonical"')

    def test_collector_service_is_public_and_indexable(self):
        response = self.client.get(reverse('core:collector-service'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'СКлад — сервис коллекционера')
        self.assertContains(response, 'электронный каталог коллекции')
        self.assertContains(response, 'content="index,follow"')
        self.assertEqual(response.content.count(b'<h1'), 1)

    def test_collector_service_does_not_redirect_authenticated_user(self):
        user = get_user_model().objects.create_user('collector', password='secret123')
        self.client.force_login(user)
        response = self.client.get(reverse('core:collector-service'))
        self.assertEqual(response.status_code, 200)

    def test_robots_blocks_private_routes_and_points_to_sitemap(self):
        response = self.client.get(reverse('robots-txt'), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
        for path in ('/admin/', '/studio/', '/api/', '/archive/', '/profile/', '/settings/', '/messages/', '/accounts/'):
            self.assertContains(response, f'Disallow: {path}')
        self.assertContains(response, 'Sitemap: https://testserver/sitemap.xml')

    def test_sitemap_contains_public_seo_pages_not_private_pages(self):
        response = self.client.get(reverse('sitemap'), secure=True)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for path in ('https://testserver/', '/service-kollekcionera/', '/news/', '/reviews/', '/market/'):
            self.assertIn(path, content)
        for path in ('/admin/', '/archive/', '/profile/', '/settings/', '/messages/'):
            self.assertNotIn(path, content)
