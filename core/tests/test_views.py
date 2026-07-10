"""Smoke tests and moderation checks for the core views."""
from __future__ import annotations

import io
import json
import zipfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import ArchiveState, Profile, Rubric
from core.services import subscriptions


class ArchiveViewTests(TestCase):
    """Ensure the archive dashboard renders successfully."""

    def test_archive_page_renders(self) -> None:
        response = self.client.get(reverse("core:archive"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ваш архив", status_code=200)


class LandingRedirectTests(TestCase):
    """Verify the landing page redirects authenticated users correctly."""

    def test_landing_redirects_authenticated_user_to_archive(self) -> None:
        user = get_user_model().objects.create_user("auth_user", password="pass1234")
        self.client.force_login(user)

        response = self.client.get(reverse("core:landing"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], reverse("core:archive"))


class PublicDocumentTests(TestCase):
    def test_information_placeholders_are_public_and_private_data_free(self) -> None:
        for route_name in ("core:about", "core:contacts", "core:requisites"):
            response = self.client.get(reverse(route_name))

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Раздел готовится")
            self.assertNotContains(response, "mailto:")
            self.assertNotContains(response, "tel:")

    def test_terms_page_does_not_link_to_requisites(self) -> None:
        response = self.client.get(reverse("core:terms"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("core:requisites"))


class SettingsSubscriptionTests(TestCase):
    def setUp(self) -> None:
        subscriptions.seed_default_plans()
        self.user = get_user_model().objects.create_user("subscriber", password="pass1234")
        Profile.objects.create(user=self.user, terms_version_accepted=settings.TERMS_VERSION)

    def test_subscriptions_page_is_removed(self) -> None:
        response = self.client.get("/subscriptions/")

        self.assertEqual(response.status_code, 404)

    def test_settings_displays_exact_subscription_prices(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "99 ₽/месяц")
        self.assertContains(response, "990 ₽/год")
        self.assertContains(response, "199 ₽/месяц")
        self.assertContains(response, "1 990 ₽/год")
        self.assertContains(response, "Оплатить 99 ₽")
        self.assertContains(response, "Оплатить 990 ₽")
        self.assertContains(response, "Оплатить 199 ₽")
        self.assertContains(response, "Оплатить 1 990 ₽")


class PublicCollectionTests(TestCase):
    def setUp(self) -> None:
        User = get_user_model()
        self.user = User.objects.create_user("collector", password="pass1234")
        Profile.objects.create(user=self.user, terms_version_accepted=settings.TERMS_VERSION)
        ArchiveState.objects.create(
            user=self.user,
            data={
                "rubrics": [
                    {
                        "id": "rubric-1",
                        "name": "Paintings",
                        "publicEnabled": True,
                        "publicSlug": "paintings",
                        "mode": "file",
                        "fields": [
                            {"id": "photo", "label": "Photo", "type": "image"},
                            {"id": "title", "label": "Title", "type": "text"},
                            {"id": "description", "label": "Description", "type": "textarea"},
                        ],
                        "files": [
                            {
                                "id": "file-1",
                                "status": "sell",
                                "values": {
                                    "photo": {"items": [{"id": "img-1", "src": "data:image/png;base64,abc"}]},
                                    "title": "Sunset",
                                    "description": "Oil on canvas",
                                    "private_note": "private-note-value",
                                },
                            }
                        ],
                    },
                    {
                        "id": "rubric-2",
                        "name": "Private",
                        "publicEnabled": False,
                        "publicSlug": "private",
                        "mode": "file",
                        "fields": [{"id": "title", "label": "Title", "type": "text"}],
                        "files": [{"id": "file-2", "values": {"title": "Secret"}}],
                    },
                ]
            },
        )

    def test_public_collection_renders_allowed_fields(self) -> None:
        response = self.client.get(reverse("core:public-collection", args=["collector", "paintings"]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paintings")
        self.assertContains(response, "publicCollectionData")
        self.assertContains(response, "Sunset")
        self.assertContains(response, "Готов продать")
        self.assertContains(response, "Oil on canvas")
        self.assertNotContains(response, "private-note-value")

    def test_private_collection_is_unavailable(self) -> None:
        response = self.client.get(reverse("core:public-collection", args=["collector", "private"]))

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Коллекция недоступна", status_code=404)


class RubricExportTests(TestCase):
    def setUp(self) -> None:
        User = get_user_model()
        self.user = User.objects.create_user("exporter", password="pass1234")
        self.other = User.objects.create_user("stranger", password="pass1234")
        Profile.objects.create(user=self.user, terms_version_accepted=settings.TERMS_VERSION)
        Profile.objects.create(user=self.other, terms_version_accepted=settings.TERMS_VERSION)
        ArchiveState.objects.create(
            user=self.user,
            data={
                "rubrics": [
                    {
                        "id": "rubric-export",
                        "name": "Paintings",
                        "mode": "file",
                        "fields": [
                            {"id": "photo", "label": "Photo", "type": "image"},
                            {"id": "title", "label": "Title", "type": "text"},
                            {"id": "description", "label": "Description", "type": "textarea"},
                        ],
                        "files": [
                            {
                                "id": "file-1",
                                "status": "sell",
                                "createdAt": 1700000000000,
                                "updatedAt": 1700003600000,
                                "values": {
                                    "photo": {"items": [{"id": "front.png", "src": "data:image/png;base64,abc"}]},
                                    "title": "Sunset",
                                    "description": "Oil on canvas",
                                    "private_note": "hidden",
                                },
                            }
                        ],
                    }
                ]
            },
        )

    def test_exports_visible_fields_to_xlsx(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:export-rubric", args=["rubric-export", "xlsx"]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("Paintings_export.xlsx", response["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(response.content)) as workbook:
            sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("Sunset", sheet_xml)
        self.assertIn("Oil on canvas", sheet_xml)
        self.assertIn("front.png", sheet_xml)
        self.assertNotIn("hidden", sheet_xml)

    def test_exports_rubric_to_pdf(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:export-rubric", args=["rubric-export", "pdf"]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("Paintings_export.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_other_user_cannot_export_rubric_by_direct_url(self) -> None:
        self.client.force_login(self.other)

        response = self.client.get(reverse("core:export-rubric", args=["rubric-export", "xlsx"]))

        self.assertEqual(response.status_code, 404)


class ArchiveApiModerationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("moder", password="pass1234")
        self.profile = Profile.objects.create(user=self.user, terms_version_accepted=settings.TERMS_VERSION)
        self.rubric = Rubric.objects.create(
            profile=self.profile,
            name="Материалы",
            slug="materials",
            is_text_mode=False,
            field_schema=[],
        )
        self.client.force_login(self.user)

    def test_rejects_banned_title(self):
        response = self.client.post(
            reverse("core:create-file"),
            data={
                "rubric": self.rubric.pk,
                "title": "Спамовое объявление",
                "data": json.dumps({"body": "пример"}),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("title", response.json().get("errors", {}))

    def test_detects_duplicate_title(self):
        first = self.client.post(
            reverse("core:create-file"),
            data={"rubric": self.rubric.pk, "title": "Каталог", "data": json.dumps({})},
        )
        self.assertEqual(first.status_code, 200)
        duplicate = self.client.post(
            reverse("core:create-file"),
            data={"rubric": self.rubric.pk, "title": "Каталог", "data": json.dumps({})},
        )
        self.assertEqual(duplicate.status_code, 400)
        errors = duplicate.json().get("errors", {})
        self.assertIn("title", errors)
        self.assertIn("ID", errors["title"][0])

    def test_detects_duplicate_content(self):
        self.client.post(
            reverse("core:create-file"),
            data={"rubric": self.rubric.pk, "title": "Первый", "data": json.dumps({"body": "текст"})},
        )
        second = self.client.post(
            reverse("core:create-file"),
            data={"rubric": self.rubric.pk, "title": "Второй", "data": json.dumps({"body": "текст"})},
        )
        self.assertEqual(second.status_code, 400)
        self.assertIn("__all__", second.json().get("errors", {}))


class RegistrationTermsFlowTests(TestCase):
    def test_register_requires_terms_acceptance(self):
        response = self.client.post(
            reverse("core:register"),
            data={
                "username": "terms_required_user",
                "email": "terms_required@example.com",
                "password1": "StrongPass!123",
                "password2": "StrongPass!123",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("terms", response.json().get("errors", {}))
        self.assertFalse(get_user_model().objects.filter(username="terms_required_user").exists())

    def test_register_with_terms_creates_user_profile_and_marks_acceptance(self):
        response = self.client.post(
            reverse("core:register"),
            data={
                "username": "terms_ok_user",
                "email": "terms_ok@example.com",
                "password1": "StrongPass!123",
                "password2": "StrongPass!123",
                "terms_accepted": "1",
                "terms_version": settings.TERMS_VERSION,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("success"))

        user = get_user_model().objects.get(username="terms_ok_user")
        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.terms_version_accepted, settings.TERMS_VERSION)
        self.assertIsNotNone(profile.terms_accepted_at)
