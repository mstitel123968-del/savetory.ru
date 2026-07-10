"""Tests for «Ваш архив → В Маркет → Аукцион»: materialising a JSON archive
card into a real ArchiveFile and starting the auction draft flow."""
from __future__ import annotations

import base64
import json
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import ArchiveFile, ArchiveFileImage, Profile, Rubric

from ..models import Listing, ListingImage

_MEDIA = tempfile.mkdtemp(prefix="auction_from_card_")
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
_DATA_URL = "data:image/png;base64," + base64.b64encode(_PNG).decode()


@override_settings(MEDIA_ROOT=_MEDIA)
class AuctionFromCardTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="seller", password="p")
        self.other = User.objects.create_user(username="other", password="p")
        for u in (self.user, self.other):
            Profile.objects.create(user=u, terms_version_accepted=settings.TERMS_VERSION)
        self.client = Client()
        self.client.force_login(self.user)
        self.now = timezone.now()

    def _post_card(self, card_id="card-abc-1", title="Старинная ваза", images=None):
        payload = {"card": {"card_id": card_id, "title": title, "description": "Фарфор",
                            "rubric": "Личное", "images": images if images is not None else [_DATA_URL]}}
        return self.client.post(reverse("market_api_auction_draft_create"),
                                data=json.dumps(payload), content_type="application/json")

    def _draft_detail(self, lid):
        return self.client.get(reverse("market_api_auction_draft_manage", args=[lid]))

    def _fill_and_publish(self, lid):
        self.client.patch(reverse("market_api_auction_draft_manage", args=[lid]),
                          data=json.dumps({"category": "collecting", "condition": "good",
                                           "auction_start_price": "1000", "auction_step": "100",
                                           "delivery_methods": ["pickup"], "auction_duration_minutes": 180}),
                          content_type="application/json")
        return self.client.post(reverse("market_api_auction_draft_publish", args=[lid]))

    # -- core fix -------------------------------------------------------------
    def test_card_payload_materializes_archive_file_and_draft(self):
        resp = self._post_card()
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], Listing.Status.DRAFT)
        # A real ArchiveFile was created, keyed by the SPA card id.
        af = ArchiveFile.objects.get(owner=self.user, data__archive_card_id="card-abc-1")
        self.assertEqual(af.title, "Старинная ваза")
        self.assertEqual(af.rubric.name, "Аукцион")
        self.assertTrue(af.rubric.is_system)
        self.assertTrue(af.rubric.field_schema)
        listing = Listing.objects.get(pk=data["listing_id"])
        self.assertEqual(listing.item_id, af.pk)  # lot linked to the ArchiveFile

    def test_direct_card_without_rubric_uses_auction_rubric_and_photos(self):
        payload = {"card": {"card_id": "direct-no-rubric", "title": "Фото-лот",
                            "description": "Создано из аукциона", "images": [_DATA_URL, _DATA_URL]}}
        resp = self.client.post(reverse("market_api_auction_draft_create"),
                                data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        listing_id = resp.json()["listing_id"]
        af = ArchiveFile.objects.get(owner=self.user, data__archive_card_id="direct-no-rubric")
        self.assertEqual(af.rubric.name, "Аукцион")
        self.assertEqual(ArchiveFileImage.objects.filter(archive_file=af).count(), 2)
        self.assertEqual(ListingImage.objects.filter(listing_id=listing_id).count(), 2)

    def test_no_card_not_found_error(self):
        resp = self._post_card(card_id="file-xyz-generated")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["ok"])
        # The old «Карточка не найдена» must not appear.
        self.assertNotIn("не найдена", resp.content.decode("utf-8").lower())

    def test_repeat_returns_same_draft(self):
        first = self._post_card().json()
        second = self._post_card().json()
        self.assertEqual(first["listing_id"], second["listing_id"])
        self.assertEqual(ArchiveFile.objects.filter(owner=self.user, data__archive_card_id="card-abc-1").count(), 1)
        self.assertEqual(Listing.objects.filter(seller=self.user, type=Listing.Type.AUCTION).count(), 1)

    def test_existing_archive_file_found_by_pk(self):
        lid = self._post_card().json()["listing_id"]
        af = ArchiveFile.objects.get(owner=self.user, data__archive_card_id="card-abc-1")
        # Posting the real pk returns the same draft (no duplicate).
        resp = self.client.post(reverse("market_api_auction_draft_create"),
                                data=json.dumps({"file_id": af.pk}), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["listing_id"], lid)

    def test_foreign_card_pk_forbidden(self):
        foreign_rubric = Rubric.objects.create(profile=self.other.profile, name="Чужое", slug="foreign")
        foreign = ArchiveFile.objects.create(rubric=foreign_rubric, title="Чужая вещь", data={})
        resp = self.client.post(reverse("market_api_auction_draft_create"),
                                data=json.dumps({"file_id": foreign.pk}), content_type="application/json")
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Listing.objects.filter(item=foreign).exists())

    def test_active_lot_not_duplicated(self):
        lid = self._post_card().json()["listing_id"]
        self._fill_and_publish(lid)
        again = self._post_card().json()
        self.assertEqual(again["listing_id"], lid)
        self.assertIn(again["status"], (Listing.Status.ACTIVE, Listing.Status.SCHEDULED))
        self.assertTrue(again["published_url"])
        self.assertEqual(Listing.objects.filter(seller=self.user, type=Listing.Type.AUCTION).count(), 1)

    def test_photos_and_cover_transferred(self):
        lid = self._post_card(images=[_DATA_URL, _DATA_URL]).json()["listing_id"]
        af = ArchiveFile.objects.get(owner=self.user, data__archive_card_id="card-abc-1")
        self.assertEqual(ArchiveFileImage.objects.filter(archive_file=af).count(), 2)
        detail = self._draft_detail(lid).json()
        self.assertEqual(len(detail["images"]), 2)
        self.assertEqual(sum(1 for i in detail["images"] if i["is_cover"]), 1)
        # Published lot keeps the images + cover.
        self._fill_and_publish(lid)
        self.assertEqual(ListingImage.objects.filter(listing_id=lid).count(), 2)

    def test_publish_redirects_to_auction_detail(self):
        lid = self._post_card().json()["listing_id"]
        resp = self._fill_and_publish(lid)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["redirect"], reverse("market_auction_detail", args=[lid]))

    def test_card_status_by_card_id(self):
        self._post_card()
        resp = self.client.get(reverse("market_api_auction_card_status_by_card") + "?card_id=card-abc-1")
        data = resp.json()
        self.assertTrue(data["has_lot"])
        self.assertTrue(data["is_draft"])
