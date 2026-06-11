"""Smoke tests and moderation checks for the core views."""
from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Profile, Rubric


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
