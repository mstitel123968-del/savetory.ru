"""Tests for seller management, cancellation, finalization and re-listing."""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import ArchiveFile, Profile, Rubric

from ..models import AuctionBid, Listing, ListingImage
from ..services import auction as auction_service
from ..services import bidding

_MEDIA = tempfile.mkdtemp(prefix="auction_mgmt_")


@override_settings(MEDIA_ROOT=_MEDIA)
class AuctionManagementTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="seller", password="p")
        self.alice = User.objects.create_user(username="alice", password="p")
        self.bob = User.objects.create_user(username="bob", password="p")
        self.admin = User.objects.create_user(username="moder", password="p", is_staff=True)
        for u in (self.owner, self.alice, self.bob, self.admin):
            Profile.objects.create(user=u, terms_version_accepted=settings.TERMS_VERSION)
        self.rubric = Rubric.objects.create(profile=self.owner.profile, name="Картины", slug="kartiny",
                                             is_text_mode=False, field_schema=[])
        self.card = ArchiveFile.objects.create(rubric=self.rubric, title="Ваза", data={})
        self.now = timezone.now()

    def make_auction(self, with_image=False, **over):
        params = dict(
            item=self.card, seller=self.owner, type=Listing.Type.AUCTION, status=Listing.Status.ACTIVE,
            category=Listing.Category.COLLECTING, item_condition="good", location="Москва",
            auction_start=self.now - timedelta(minutes=10), auction_end=self.now + timedelta(hours=2),
            auction_start_price=Decimal("1000.00"), auction_step=Decimal("100.00"),
            auction_auto_extend=False, auction_auto_extend_minutes=2, delivery_methods=["pickup"], is_active=True,
        )
        params.update(over)
        lot = Listing(**params)
        lot.save()
        Listing.objects.filter(pk=lot.pk).update(current_price=None)
        lot.refresh_from_db()
        if with_image:
            ListingImage.objects.create(listing=lot, image=SimpleUploadedFile("c.png", b"\x89PNG\r\n\x1a\n" + b"0" * 16, content_type="image/png"), display_order=0, is_cover=True)
        return lot

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c

    def _expire(self, lot):
        Listing.objects.filter(pk=lot.pk).update(auction_end=self.now - timedelta(minutes=1))
        lot.refresh_from_db()

    # -- manage edit ----------------------------------------------------------
    def test_edit_before_first_bid(self):
        lot = self.make_auction()
        resp = self._client(self.owner).patch(reverse("market_api_auction_manage", args=[lot.pk]),
                                               data=json.dumps({"title": "Новое имя", "auction_start_price": "1500"}),
                                               content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        lot.refresh_from_db()
        self.assertEqual(lot.title, "Новое имя")
        self.assertEqual(lot.auction_start_price, Decimal("1500.00"))

    def test_critical_change_blocked_after_bid(self):
        lot = self.make_auction()
        bidding.place_bid(self.bob, lot.pk, Decimal("1000.00"))
        resp = self._client(self.owner).patch(reverse("market_api_auction_manage", args=[lot.pk]),
                                               data=json.dumps({"auction_start_price": "2000"}),
                                               content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("auction_start_price", resp.json()["errors"])
        lot.refresh_from_db()
        self.assertEqual(lot.auction_start_price, Decimal("1000.00"))

    def test_allowed_change_after_bid(self):
        lot = self.make_auction()
        bidding.place_bid(self.bob, lot.pk, Decimal("1000.00"))
        resp = self._client(self.owner).patch(reverse("market_api_auction_manage", args=[lot.pk]),
                                               data=json.dumps({"description": "Уточнение", "location": "Тверь"}),
                                               content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        lot.refresh_from_db()
        self.assertEqual(lot.location, "Тверь")

    def test_manage_only_own_lot(self):
        lot = self.make_auction()
        resp = self._client(self.alice).patch(reverse("market_api_auction_manage", args=[lot.pk]),
                                              data=json.dumps({"description": "x"}), content_type="application/json")
        self.assertEqual(resp.status_code, 403)

    # -- cancellation ---------------------------------------------------------
    def test_cancel_without_bids(self):
        lot = self.make_auction()
        resp = self._client(self.owner).post(reverse("market_api_auction_cancel", args=[lot.pk]),
                                             data=json.dumps({"reason": "Передумал"}), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        lot.refresh_from_db()
        self.assertEqual(lot.status, Listing.Status.CANCELLED)
        self.assertFalse(lot.is_active)
        self.assertEqual(lot.auction_result, Listing.AuctionResult.CANCELLED)
        self.assertEqual(lot.cancellation_reason, "Передумал")
        self.assertIsNotNone(lot.cancelled_at)

    def test_cancel_is_idempotent(self):
        lot = self.make_auction()
        url = reverse("market_api_auction_cancel", args=[lot.pk])
        self._client(self.owner).post(url, data=json.dumps({"reason": "a"}), content_type="application/json")
        resp = self._client(self.owner).post(url, data=json.dumps({"reason": "b"}), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AuctionBid.objects.filter(listing=lot).count(), 0)

    def test_seller_cannot_cancel_after_bid(self):
        lot = self.make_auction()
        bidding.place_bid(self.bob, lot.pk, Decimal("1000.00"))
        resp = self._client(self.owner).post(reverse("market_api_auction_cancel", args=[lot.pk]),
                                             data=json.dumps({"reason": "x"}), content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        lot.refresh_from_db()
        self.assertEqual(lot.status, Listing.Status.ACTIVE)

    def test_admin_cancel_after_bid(self):
        lot = self.make_auction()
        bidding.place_bid(self.bob, lot.pk, Decimal("1000.00"))
        resp = self._client(self.admin).post(reverse("market_api_auction_cancel", args=[lot.pk]),
                                             data=json.dumps({"reason": "Нарушение правил"}), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        lot.refresh_from_db()
        self.assertEqual(lot.status, Listing.Status.CANCELLED)
        self.assertTrue(lot.is_admin_cancelled)
        self.assertEqual(lot.cancelled_by_id, self.admin.id)
        self.assertIsNone(lot.winner_id)
        # Bid history preserved.
        self.assertEqual(AuctionBid.objects.filter(listing=lot).count(), 1)

    def test_admin_cancel_requires_reason(self):
        lot = self.make_auction()
        bidding.place_bid(self.bob, lot.pk, Decimal("1000.00"))
        resp = self._client(self.admin).post(reverse("market_api_auction_cancel", args=[lot.pk]),
                                             data=json.dumps({}), content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("reason", resp.json()["errors"])

    # -- finalization ---------------------------------------------------------
    def test_finalize_no_bids(self):
        lot = self.make_auction()
        self._expire(lot)
        bidding.finalize_auction(lot)
        lot.refresh_from_db()
        self.assertEqual(lot.status, Listing.Status.COMPLETED)
        self.assertEqual(lot.auction_result, Listing.AuctionResult.NO_BIDS)
        self.assertIsNone(lot.winner_id)
        self.assertIsNotNone(lot.completed_at)

    def test_finalize_with_winner(self):
        lot = self.make_auction()
        bidding.place_bid(self.alice, lot.pk, Decimal("1000.00"))
        bidding.place_bid(self.bob, lot.pk, Decimal("1100.00"))
        self._expire(lot)
        bidding.finalize_auction(lot)
        lot.refresh_from_db()
        self.assertEqual(lot.auction_result, Listing.AuctionResult.SOLD)
        self.assertEqual(lot.winner_id, self.bob.id)
        self.assertEqual(lot.winning_bid.amount, Decimal("1100.00"))

    def test_finalize_reserve_not_reached(self):
        lot = self.make_auction(auction_reserve_price=Decimal("2000.00"))
        bidding.place_bid(self.alice, lot.pk, Decimal("500.00"))
        self._expire(lot)
        bidding.finalize_auction(lot)
        lot.refresh_from_db()
        self.assertEqual(lot.auction_result, Listing.AuctionResult.RESERVE_NOT_REACHED)
        self.assertIsNone(lot.winner_id)
        self.assertEqual(lot.winning_bid.amount, Decimal("500.00"))

    def test_refinalize_keeps_result(self):
        lot = self.make_auction()
        bidding.place_bid(self.bob, lot.pk, Decimal("1000.00"))
        self._expire(lot)
        bidding.finalize_auction(lot)
        lot.refresh_from_db()
        first_completed = lot.completed_at
        bidding.finalize_auction(lot)
        lot.refresh_from_db()
        self.assertEqual(lot.completed_at, first_completed)
        self.assertEqual(lot.winner_id, self.bob.id)

    def test_no_bids_after_completion(self):
        lot = self.make_auction()
        self._expire(lot)
        bidding.finalize_auction(lot)
        with self.assertRaises(bidding.BidError) as ctx:
            bidding.place_bid(self.bob, lot.pk, Decimal("1000.00"))
        self.assertEqual(ctx.exception.code, "auction_ended")

    def test_management_command_finalizes(self):
        lot = self.make_auction()
        bidding.place_bid(self.bob, lot.pk, Decimal("1000.00"))
        self._expire(lot)
        call_command("finalize_auctions")
        lot.refresh_from_db()
        self.assertEqual(lot.status, Listing.Status.COMPLETED)
        self.assertEqual(lot.winner_id, self.bob.id)

    # -- card sync ------------------------------------------------------------
    def test_archive_card_status_after_finalize(self):
        lot = self.make_auction()
        bidding.place_bid(self.bob, lot.pk, Decimal("1000.00"))
        self._expire(lot)
        bidding.finalize_auction(lot)
        state = auction_service.card_auction_state(self.owner, self.card)
        self.assertEqual(state["status_label"], "Продано")
        self.assertTrue(state["is_finished"])

    # -- relist ---------------------------------------------------------------
    def test_relist_creates_fresh_draft(self):
        lot = self.make_auction(with_image=True)
        bidding.place_bid(self.bob, lot.pk, Decimal("1000.00"))
        self._expire(lot)
        bidding.finalize_auction(lot)
        resp = self._client(self.owner).post(reverse("market_api_auction_relist", args=[lot.pk]))
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        new_id = data["listing_id"]
        self.assertNotEqual(new_id, lot.pk)
        draft = Listing.objects.get(pk=new_id)
        self.assertEqual(draft.status, Listing.Status.DRAFT)
        self.assertEqual(draft.title, lot.title)
        # Images carried over, bids/winner/current_price/result NOT.
        self.assertEqual(ListingImage.objects.filter(listing=draft).count(), 1)
        self.assertEqual(AuctionBid.objects.filter(listing=draft).count(), 0)
        self.assertIsNone(draft.current_price)
        self.assertIsNone(draft.winner_id)
        self.assertEqual(draft.auction_result, "")
        self.assertIsNone(draft.auction_start)
        # Original lot is untouched.
        lot.refresh_from_db()
        self.assertEqual(lot.status, Listing.Status.COMPLETED)
        self.assertEqual(lot.winner_id, self.bob.id)
