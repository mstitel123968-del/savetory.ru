import tempfile
from pathlib import Path
from django.test import SimpleTestCase, override_settings
from django.urls import reverse


@override_settings(ALLOWED_HOSTS=['testserver'])
class DownloadSiteTests(SimpleTestCase):
    def test_home_and_unavailable_android(self):
        with override_settings(SKLAD_ANDROID_FILE='/missing/sklad.apk'):
            response = self.client.get('/')
        self.assertContains(response, 'простой архив')
        self.assertContains(response, 'Скачать APK')
        self.assertNotContains(response, 'Для Windows 10')
        self.assertNotContains(response, 'Android 7')
        self.assertNotContains(response, '/api/auth/')

    def test_binary_download_and_missing_package(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'app.exe'
            source.write_bytes(b'test-package')
            with override_settings(SKLAD_WINDOWS_FILE=str(source)):
                response = self.client.get(reverse('core:download', args=['windows']))
                self.assertEqual(b''.join(response.streaming_content), b'test-package')
                self.assertIn('attachment', response['Content-Disposition'])
            with override_settings(SKLAD_ANDROID_FILE=str(source.with_suffix('.apk'))):
                self.assertEqual(self.client.get('/download/android/').status_code, 404)
        self.assertEqual(self.client.get('/download/unknown/').status_code, 404)

    def test_old_site_is_not_accessible(self):
        for url in ('/archive/', '/profile/', '/market/', '/community/', '/settings/'):
            self.assertRedirects(self.client.get(url), '/')
        self.assertEqual(self.client.post('/api/auth/register/').status_code, 405)
