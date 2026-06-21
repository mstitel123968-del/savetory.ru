"""Tests for the auction draft → publish JSON API."""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import ArchiveFile, ArchiveFileImage, Profile, Rubric

from ..models import Listing, ListingImage

_MEDIA_ROOT = tempfile.mkdtemp(prefix="market_auction_api_")

_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _image_file(name):
    return SimpleUploadedFile(name, _PNG, content_type="image/png")


@override_settings(MEDIA_ROOT=_MEDIA_ROOT)
class AuctionDraftApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="pass123")
        self.other = User.objects.create_user(username="other", password="pass123")
        for user in (self.owner, self.other):
            Profile.objects.create(user=user, terms_version_accepted=settings.TERMS_VERSION)
        self.rubric = Rubric.objects.create(profile=self.owner.profile, name="Картины", slug="kartiny",
                                             is_text_mode=False, field_schema=[])
        self.card = ArchiveFile.objects.create(rubric=self.rubric, title="Старинная ваза",
                                                data={"description": "Фарфор, XIX век"})
        self.img1 = ArchiveFileImage.objects.create(archive_file=self.card, image=_image_file("a.png"), display_order=0)
        self.img2 = ArchiveFileImage.objects.create(archive_file=self.card, image=_image_file("b.png"), display_order=1)
        self.client = Client()
        self.client.force_login(self.owner)

    # -- helpers --------------------------------------------------------------
    def _create_draft(self, client=None):
        client = client or self.client
        return client.post(reverse("market_api_auction_draft_create"),
                           data=json.dumps({"file_id": self.card.pk}), content_type="application/json")

    def _manage_url(self, lid):
        return reverse("market_api_auction_draft_manage", args=[lid])

    def _patch(self, lid, payload):
        return self.client.patch(self._manage_url(lid), data=json.dumps(payload), content_type="application/json")

    def _fill_required(self, lid, **over):
        payload = {
            "category": "collecting", "condition": "good",
            "auction_start_price": "100", "auction_step": "10",
            "delivery_methods": ["pickup"], "auction_duration_minutes": 180,
        }
        payload.update(over)
        return self._patch(lid, payload)

    def _card_status_url(self):
        return reverse("market_api_auction_card_status", args=[self.card.pk])

    # -- read-only card status ------------------------------------------------
    def test_card_status_no_lot(self):
        data = self.client.get(self._card_status_url()).json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["has_lot"])

    def test_card_status_reports_draft(self):
        self._create_draft()
        data = self.client.get(self._card_status_url()).json()
        self.assertTrue(data["has_lot"])
        self.assertEqual(data["status"], Listing.Status.DRAFT)
        self.assertTrue(data["is_draft"])

    def test_card_status_reports_published(self):
        lid = self._create_draft().json()["listing_id"]
        self._fill_required(lid)
        self.client.post(reverse("market_api_auction_draft_publish", args=[lid]))
        data = self.client.get(self._card_status_url()).json()
        self.assertTrue(data["has_lot"])
        self.assertFalse(data["is_draft"])
        self.assertTrue(data["listing_url"])

    # -- creation -------------------------------------------------------------
    def test_create_draft_by_owner(self):
        resp = self._create_draft()
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], Listing.Status.DRAFT)
        self.assertEqual(data["rubric"], "Картины")
        self.assertEqual(data["image_count"], 2)

    def test_foreign_card_forbidden(self):
        self.client.force_login(self.other)
        resp = self._create_draft()
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Listing.objects.filter(item=self.card, seller=self.other).exists())

    def test_repeat_returns_same_draft(self):
        first = self._create_draft().json()
        second = self._create_draft().json()
        self.assertEqual(first["listing_id"], second["listing_id"])
        self.assertEqual(Listing.objects.filter(item=self.card, seller=self.owner, status=Listing.Status.DRAFT).count(), 1)
        # No duplicated images on the repeat call.
        self.assertEqual(ListingImage.objects.filter(listing_id=first["listing_id"]).count(), 2)

    def test_title_and_description_transferred(self):
        data = self._create_draft().json()
        self.assertEqual(data["title"], "Старинная ваза")
        self.assertEqual(data["description"], "Фарфор, XIX век")

    def test_images_and_order_copied_with_single_cover(self):
        data = self._create_draft().json()
        images = data["images"]
        self.assertEqual([i["order"] for i in images], [0, 1])
        self.assertEqual([i["is_cover"] for i in images], [True, False])
        self.assertEqual(sum(1 for i in images if i["is_cover"]), 1)
        for image in images:
            self.assertTrue(image["url"])
        # Source link preserved.
        lot_images = ListingImage.objects.filter(listing_id=data["listing_id"]).order_by("display_order")
        self.assertEqual([li.source_image_id for li in lot_images], [self.img1.id, self.img2.id])

    def test_published_lot_not_duplicated(self):
        lid = self._create_draft().json()["listing_id"]
        self._fill_required(lid)
        self.client.post(reverse("market_api_auction_draft_publish", args=[lid]))
        # Re-requesting a draft returns the published lot, not a new draft.
        resp = self._create_draft()
        data = resp.json()
        self.assertEqual(data["listing_id"], lid)
        self.assertIn(data["status"], (Listing.Status.ACTIVE, Listing.Status.SCHEDULED))
        self.assertTrue(data["published_url"])
        self.assertEqual(Listing.objects.filter(item=self.card, seller=self.owner).count(), 1)

    # -- partial update -------------------------------------------------------
    def test_partial_save(self):
        lid = self._create_draft().json()["listing_id"]
        resp = self._patch(lid, {"location": "Москва"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["location"], "Москва")
        # Untouched fields remain.
        self.assertEqual(resp.json()["title"], "Старинная ваза")

    def test_unknown_field_rejected(self):
        lid = self._create_draft().json()["listing_id"]
        resp = self._patch(lid, {"bogus": 1})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("bogus", resp.json()["errors"])

    def test_patch_only_own_draft(self):
        lid = self._create_draft().json()["listing_id"]
        self.client.force_login(self.other)
        resp = self._patch(lid, {"location": "Тверь"})
        self.assertEqual(resp.status_code, 403)

    def test_delivery_method_errors(self):
        lid = self._create_draft().json()["listing_id"]
        dup = self._patch(lid, {"delivery_methods": ["pickup", "pickup"]})
        self.assertEqual(dup.status_code, 400)
        self.assertIn("delivery_methods", dup.json()["errors"])
        bad_cost = self._patch(lid, {"delivery_methods": ["pickup"], "delivery_cost": "300"})
        self.assertEqual(bad_cost.status_code, 400)
        self.assertIn("delivery_cost", bad_cost.json()["errors"])

    def test_cover_change_keeps_single_cover(self):
        data = self._create_draft().json()
        lid = data["listing_id"]
        second_id = data["images"][1]["id"]
        resp = self._patch(lid, {"cover_image_id": second_id})
        self.assertEqual(resp.status_code, 200, resp.content)
        covers = [i for i in resp.json()["images"] if i["is_cover"]]
        self.assertEqual(len(covers), 1)
        self.assertEqual(covers[0]["id"], second_id)

    def test_exclude_image_keeps_archive_original(self):
        data = self._create_draft().json()
        lid = data["listing_id"]
        excluded = data["images"][0]["id"]
        resp = self._patch(lid, {"excluded_image_ids": [excluded]})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(resp.json()["images"]), 1)
        # Archive image untouched.
        self.assertTrue(ArchiveFileImage.objects.filter(pk=self.img1.id).exists())
        self.assertEqual(ArchiveFileImage.objects.filter(archive_file=self.card).count(), 2)
        # Exactly one cover remains.
        self.assertEqual(sum(1 for i in resp.json()["images"] if i["is_cover"]), 1)

    # -- publish --------------------------------------------------------------
    def test_publish_now(self):
        lid = self._create_draft().json()["listing_id"]
        self._fill_required(lid)
        resp = self.client.post(reverse("market_api_auction_draft_publish", args=[lid]))
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], Listing.Status.ACTIVE)
        self.assertEqual(data["redirect"], reverse("market_auction_detail", args=[lid]))

    def test_publish_scheduled(self):
        lid = self._create_draft().json()["listing_id"]
        start = (timezone.now() + timedelta(days=1)).replace(microsecond=0)
        self._fill_required(lid, auction_start_mode="scheduled", auction_start=start.isoformat())
        resp = self.client.post(reverse("market_api_auction_draft_publish", args=[lid]))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["status"], Listing.Status.SCHEDULED)
        listing = Listing.objects.get(pk=lid)
        self.assertEqual(listing.auction_start, start)

    def test_end_computed_from_publication_time(self):
        lid = self._create_draft().json()["listing_id"]
        self._fill_required(lid, auction_duration_minutes=120)
        # Force an old creation time to prove publication time is used, not it.
        Listing.objects.filter(pk=lid).update(created_at=timezone.now() - timedelta(days=5))
        before = timezone.now()
        self.client.post(reverse("market_api_auction_draft_publish", args=[lid]))
        listing = Listing.objects.get(pk=lid)
        self.assertGreaterEqual(listing.auction_start, before - timedelta(seconds=5))
        self.assertAlmostEqual((listing.auction_end - listing.auction_start).total_seconds(), 120 * 60, delta=5)

    def test_publish_without_image_forbidden(self):
        lid = self._create_draft().json()["listing_id"]
        self._fill_required(lid)
        # Exclude every lot image via the API, then publishing must fail.
        image_ids = list(ListingImage.objects.filter(listing_id=lid).values_list("id", flat=True))
        self._patch(lid, {"excluded_image_ids": image_ids})
        resp = self.client.post(reverse("market_api_auction_draft_publish", args=[lid]))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("images", resp.json()["errors"])

    def test_current_price_null_after_publish(self):
        lid = self._create_draft().json()["listing_id"]
        self._fill_required(lid)
        self.client.post(reverse("market_api_auction_draft_publish", args=[lid]))
        self.assertIsNone(Listing.objects.get(pk=lid).current_price)

    def test_publish_idempotent(self):
        lid = self._create_draft().json()["listing_id"]
        self._fill_required(lid)
        first = self.client.post(reverse("market_api_auction_draft_publish", args=[lid])).json()
        start_after_first = Listing.objects.get(pk=lid).auction_start
        second = self.client.post(reverse("market_api_auction_draft_publish", args=[lid])).json()
        self.assertEqual(first["listing_id"], second["listing_id"])
        self.assertEqual(second["status"], first["status"])
        self.assertEqual(Listing.objects.get(pk=lid).auction_start, start_after_first)
        self.assertEqual(Listing.objects.filter(item=self.card, seller=self.owner).count(), 1)

    # -- delete ---------------------------------------------------------------
    def test_delete_draft(self):
        lid = self._create_draft().json()["listing_id"]
        resp = self.client.delete(self._manage_url(lid))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(Listing.objects.filter(pk=lid).exists())

    def test_delete_published_forbidden(self):
        lid = self._create_draft().json()["listing_id"]
        self._fill_required(lid)
        self.client.post(reverse("market_api_auction_draft_publish", args=[lid]))
        resp = self.client.delete(self._manage_url(lid))
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Listing.objects.filter(pk=lid).exists())
