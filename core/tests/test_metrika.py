from django.http import HttpResponse, JsonResponse
from pathlib import Path

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.middleware import MetrikaMiddleware


@override_settings(
    YANDEX_METRIKA_COUNTER_ID=111189704,
    YANDEX_METRIKA_CONSENT_COOKIE='savetory_analytics_consent',
)
class MetrikaMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def render(self, path='/', *, cookies=None, body='<body><main>ok</main></body>'):
        request = self.factory.get(path)
        request.COOKIES.update(cookies or {})
        response = HttpResponse(f'<!doctype html><html><head></head>{body}</html>')
        return MetrikaMiddleware(lambda _request: response)(request)

    def test_injects_single_global_loader_and_banner(self):
        response = self.render()
        html = response.content.decode()

        self.assertEqual(html.count('metrika.js'), 1)
        self.assertEqual(html.count('data-cookie-consent hidden'), 1)
        self.assertIn('data-counter-id="111189704"', html)
        self.assertIn('data-webvisor="true"', html)
        self.assertRegex(html, r'<body><noscript data-savetory-metrika>')
        self.assertLess(html.index('metrika.js'), html.index('</head>'))

    def test_second_pass_does_not_duplicate_counter(self):
        first = self.render()
        request = self.factory.get('/')
        second = MetrikaMiddleware(lambda _request: first)(request)

        self.assertEqual(second.content.decode().count('metrika.js'), 1)

    def test_private_page_disables_webvisor(self):
        html = self.render('/archive/').content.decode()

        self.assertIn('data-webvisor="false"', html)

    def test_external_noscript_request_requires_prior_consent(self):
        undecided = self.render('/').content.decode()
        accepted = self.render('/', cookies={'savetory_analytics_consent': 'accepted'}).content.decode()
        declined = self.render('/', cookies={'savetory_analytics_consent': 'declined'}).content.decode()

        self.assertNotIn('mc.yandex.ru/watch', undecided)
        self.assertIn('mc.yandex.ru/watch/111189704', accepted)
        self.assertNotIn('mc.yandex.ru/watch', declined)

    def test_does_not_inject_into_json_or_studio(self):
        request = self.factory.get('/api/auth/status/')
        response = MetrikaMiddleware(lambda _request: JsonResponse({'ok': True}))(request)
        self.assertNotIn(b'metrika.js', response.content)

        studio = self.render('/studio/')
        self.assertNotIn(b'metrika.js', studio.content)


class MetrikaJavascriptTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = Path(settings.BASE_DIR, 'core', 'static', 'js', 'metrika.js').read_text(encoding='utf-8')

    def test_required_counter_settings_are_present(self):
        for setting in (
            'ssr: true',
            'webvisor: webvisorEnabled',
            'clickmap: true',
            "ecommerce: 'dataLayer'",
            'accurateTrackBounce: true',
            'trackLinks: true',
            'defer: true',
            'sendTitle: false',
        ):
            self.assertIn(setting, self.source)

    def test_goal_allowlist_contains_every_requested_goal(self):
        for goal in (
            'start_click',
            'registration_open',
            'registration_code_sent',
            'registration_complete',
            'login_complete',
            'rubric_created',
            'card_created',
            'market_publish',
            'tariff_open',
            'payment_started',
            'payment_success',
        ):
            self.assertIn(f"'{goal}'", self.source)

    def test_private_content_protection_is_enabled(self):
        self.assertIn("classList.add('ym-disable-keys')", self.source)
        self.assertIn("classList.add('ym-hide-content')", self.source)
        self.assertIn("split('?')[0].split('#')[0]", self.source)
