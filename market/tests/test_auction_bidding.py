"""Tests for the server-side auction bidding mechanics."""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ArchiveFile, Profile, Rubric

from ..models import AuctionBid, Listing
from ..services import bidding


class BiddingTestBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="seller", password="pass123")
        self.alice = User.objects.create_user(username="alice", password="pass123")
        self.bob = User.objects.create_user(username="bob", password="pass123")
        for user in (self.owner, self.alice, self.bob):
            Profile.objects.create(user=user, terms_version_accepted=settings.TERMS_VERSION)
        self.rubric = Rubric.objects.create(profile=self.owner.profile, name="Картины", slug="kartiny",
                                             is_text_mode=False, field_schema=[])
        self.card = ArchiveFile.objects.create(rubric=self.rubric, title="Ваза", data={})
        self.now = timezone.now()

    def make_auction(self, **over):
        params = dict(
            item=self.card, seller=self.owner, type=Listing.Type.AUCTION, status=Listing.Status.ACTIVE,
            category=Listing.Category.COLLECTING, item_condition="good",
            auction_start=self.now - timedelta(minutes=10), auction_end=self.now + timedelta(hours=2),
            auction_start_price=Decimal("1000.00"), auction_step=Decimal("100.00"),
            auction_auto_extend=False, auction_auto_extend_minutes=2,
            delivery_methods=["pickup"], is_active=True,
        )
        params.update(over)
        listing = Listing(**params)
        listing.save()
        # Published lots keep current_price NULL until the first bid.
        Listing.objects.filter(pk=listing.pk).update(current_price=None)
        listing.refresh_from_db()
        return listing


class BiddingRuleTests(BiddingTestBase):
    def test_first_bid_uses_total_amount(self):
        lot = self.make_auction()
        result = bidding.place_bid(self.alice, lot.pk, Decimal("1100.00"))
        self.assertEqual(result["current_price"], Decimal("1100.00"))
        bid = AuctionBid.objects.get(pk=result["bid"].id)
        self.assertTrue(bid.is_winning)
        self.assertEqual(bid.previous_price, Decimal("1000.00"))
        lot.refresh_from_db()
        self.assertEqual(lot.current_price, Decimal("1100.00"))

    def test_bid_above_minimum(self):
        lot = self.make_auction()
        result = bidding.place_bid(self.alice, lot.pk, Decimal("1500.00"))
        self.assertEqual(result["current_price"], Decimal("1500.00"))

    def test_bid_below_next_total_rejected(self):
        lot = self.make_auction()
        with self.assertRaises(bidding.BidError) as ctx:
            bidding.place_bid(self.alice, lot.pk, Decimal("1099.00"))
        self.assertEqual(ctx.exception.code, "bid_too_low")
        self.assertEqual(AuctionBid.objects.filter(listing=lot).count(), 0)

    def test_next_bid_respects_step(self):
        lot = self.make_auction()
        bidding.place_bid(self.alice, lot.pk, Decimal("1100.00"))
        with self.assertRaises(bidding.BidError) as ctx:
            bidding.place_bid(self.bob, lot.pk, Decimal("1199.00"))
        self.assertEqual(ctx.exception.code, "bid_too_low")
        ok = bidding.place_bid(self.bob, lot.pk, Decimal("1200.00"))
        self.assertEqual(ok["current_price"], Decimal("1200.00"))

    def test_seller_cannot_bid(self):
        lot = self.make_auction()
        with self.assertRaises(bidding.BidError) as ctx:
            bidding.place_bid(self.owner, lot.pk, Decimal("1000.00"))
        self.assertEqual(ctx.exception.code, "seller_cannot_bid")

    def test_bid_before_start_rejected(self):
        lot = self.make_auction(status=Listing.Status.SCHEDULED,
                                auction_start=self.now + timedelta(hours=1),
                                auction_end=self.now + timedelta(hours=3))
        with self.assertRaises(bidding.BidError) as ctx:
            bidding.place_bid(self.alice, lot.pk, Decimal("1000.00"))
        self.assertEqual(ctx.exception.code, "auction_not_started")

    def test_bid_after_end_rejected(self):
        lot = self.make_auction(auction_start=self.now - timedelta(hours=2),
                                auction_end=self.now - timedelta(minutes=1))
        with self.assertRaises(bidding.BidError) as ctx:
            bidding.place_bid(self.alice, lot.pk, Decimal("1000.00"))
        self.assertEqual(ctx.exception.code, "auction_ended")

    def test_bid_on_cancelled_rejected(self):
        lot = self.make_auction()
        Listing.objects.filter(pk=lot.pk).update(status=Listing.Status.CANCELLED, is_active=False)
        with self.assertRaises(bidding.BidError) as ctx:
            bidding.place_bid(self.alice, lot.pk, Decimal("1000.00"))
        self.assertEqual(ctx.exception.code, "auction_cancelled")

    def test_invalid_amounts(self):
        for raw in ("nan", "Infinity", "-5", "10.999"):
            with self.assertRaises(bidding.BidError) as ctx:
                bidding.parse_amount(raw)
            self.assertEqual(ctx.exception.code, "invalid_amount")

    def test_current_price_and_leader_change(self):
        lot = self.make_auction()
        first = bidding.place_bid(self.alice, lot.pk, Decimal("1100.00"))
        second = bidding.place_bid(self.bob, lot.pk, Decimal("1200.00"))
        first_bid = AuctionBid.objects.get(pk=first["bid"].id)
        second_bid = AuctionBid.objects.get(pk=second["bid"].id)
        self.assertFalse(first_bid.is_winning)
        self.assertTrue(second_bid.is_winning)
        self.assertEqual(second_bid.previous_price, Decimal("1100.00"))
        lot.refresh_from_db()
        self.assertEqual(lot.current_price, Decimal("1200.00"))

    def test_leader_must_raise_by_step(self):
        lot = self.make_auction()
        bidding.place_bid(self.alice, lot.pk, Decimal("1100.00"))
        with self.assertRaises(bidding.BidError) as ctx:
            bidding.place_bid(self.alice, lot.pk, Decimal("1199.00"))
        self.assertEqual(ctx.exception.code, "already_leading")
        ok = bidding.place_bid(self.alice, lot.pk, Decimal("1200.00"))
        self.assertEqual(ok["current_price"], Decimal("1200.00"))

    def test_concurrent_bid_conflict(self):
        lot = self.make_auction()
        # Alice gets there first.
        bidding.place_bid(self.alice, lot.pk, Decimal("1100.00"))
        # Bob saw current_price=1000 before Alice's bid and now submits a stale request.
        with self.assertRaises(bidding.BidError) as ctx:
            bidding.place_bid(
                self.bob,
                lot.pk,
                Decimal("1100.00"),
                seen_minimum=Decimal("1100.00"),
                seen_current_price=Decimal("1000.00"),
            )
        self.assertEqual(ctx.exception.code, "concurrent_bid_conflict")
        self.assertEqual(ctx.exception.minimum_bid, Decimal("1200.00"))
        self.assertEqual(AuctionBid.objects.filter(listing=lot).count(), 1)

    def test_sequential_bid_increments_persist(self):
        lot = self.make_auction(auction_step=Decimal("50.00"))
        first = bidding.place_bid(self.alice, lot.pk, Decimal("1050.00"))
        self.assertEqual(first["current_price"], Decimal("1050.00"))
        lot.refresh_from_db()
        self.assertEqual(lot.current_price, Decimal("1050.00"))

        second = bidding.place_bid(self.bob, lot.pk, Decimal("1100.00"))
        self.assertEqual(second["current_price"], Decimal("1100.00"))
        lot.refresh_from_db()
        self.assertEqual(lot.current_price, Decimal("1100.00"))
        self.assertEqual(AuctionBid.objects.filter(listing=lot).count(), 2)


class AutoExtendTests(BiddingTestBase):
    def test_auto_extend_in_final_window(self):
        lot = self.make_auction(auction_auto_extend=True, auction_auto_extend_minutes=2,
                                auction_end=self.now + timedelta(minutes=1))
        result = bidding.place_bid(self.alice, lot.pk, Decimal("1100.00"))
        self.assertTrue(result["extended"])
        lot.refresh_from_db()
        self.assertGreater(lot.auction_end, self.now + timedelta(minutes=1))

    def test_no_extend_outside_window(self):
        lot = self.make_auction(auction_auto_extend=True, auction_auto_extend_minutes=2,
                                auction_end=self.now + timedelta(hours=1))
        result = bidding.place_bid(self.alice, lot.pk, Decimal("1100.00"))
        self.assertFalse(result["extended"])


class ReserveAndStateTests(BiddingTestBase):
    def test_reserve_status_transitions(self):
        lot = self.make_auction(auction_reserve_price=Decimal("1500.00"))
        self.assertEqual(bidding.reserve_status(lot), "not_reached")
        bidding.place_bid(self.alice, lot.pk, Decimal("1100.00"))
        lot.refresh_from_db()
        self.assertEqual(bidding.reserve_status(lot), "not_reached")
        bidding.place_bid(self.bob, lot.pk, Decimal("1500.00"))
        lot.refresh_from_db()
        self.assertEqual(bidding.reserve_status(lot), "reached")

    def test_state_hides_reserve_amount(self):
        lot = self.make_auction(auction_reserve_price=Decimal("1500.00"))
        client = Client()
        resp = client.get(reverse("market_api_auction_state", args=[lot.pk]))
        data = resp.json()
        self.assertEqual(data["reserve_status"], "not_reached")
        self.assertNotIn("auction_reserve_price", data)
        self.assertNotIn("1500", json.dumps(data))

    def test_scheduled_transitions_to_active_on_access(self):
        lot = self.make_auction(status=Listing.Status.SCHEDULED,
                                auction_start=self.now - timedelta(minutes=1),
                                auction_end=self.now + timedelta(hours=2))
        # Saved as scheduled; the state endpoint should activate it.
        self.assertEqual(Listing.objects.get(pk=lot.pk).status, Listing.Status.SCHEDULED)
        resp = Client().get(reverse("market_api_auction_state", args=[lot.pk]))
        self.assertEqual(resp.json()["status"], Listing.Status.ACTIVE)
        self.assertEqual(Listing.objects.get(pk=lot.pk).status, Listing.Status.ACTIVE)

    def test_active_transitions_to_completed_on_access(self):
        lot = self.make_auction(auction_start=self.now - timedelta(hours=2),
                                auction_end=self.now - timedelta(minutes=1))
        resp = Client().get(reverse("market_api_auction_state", args=[lot.pk]))
        self.assertEqual(resp.json()["status"], Listing.Status.COMPLETED)
        self.assertEqual(Listing.objects.get(pk=lot.pk).status, Listing.Status.COMPLETED)


class BidHistoryAndApiTests(BiddingTestBase):
    def test_history_is_anonymised(self):
        lot = self.make_auction()
        bidding.place_bid(self.alice, lot.pk, Decimal("1100.00"))
        resp = Client().get(reverse("market_api_auction_bids", args=[lot.pk]))
        bids = resp.json()["bids"]
        self.assertEqual(len(bids), 1)
        self.assertNotIn("alice", bids[0]["bidder"])
        self.assertTrue(bids[0]["bidder"].startswith("a"))
        self.assertTrue(bids[0]["is_winning"])

    def test_bid_api_success(self):
        lot = self.make_auction()
        client = Client()
        client.force_login(self.alice)
        resp = client.post(reverse("market_api_auction_bid", args=[lot.pk]),
                           data=json.dumps({"amount": "1100"}), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["current_price"], "1100.00")
        self.assertEqual(data["minimum_next_bid"], "1200.00")
        self.assertTrue(data["is_user_leading"])

    def test_bid_api_too_low_payload(self):
        lot = self.make_auction()
        client = Client()
        client.force_login(self.alice)
        resp = client.post(reverse("market_api_auction_bid", args=[lot.pk]),
                           data=json.dumps({"amount": "1050"}), content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["code"], "bid_too_low")
        self.assertIn("amount", data["errors"])
        self.assertEqual(data["minimum_bid"], "1100.00")

    def test_bid_api_requires_authentication(self):
        lot = self.make_auction()
        resp = Client().post(reverse("market_api_auction_bid", args=[lot.pk]),
                             data=json.dumps({"amount": "1000"}), content_type="application/json")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], "authentication_required")

    def test_buy_now_completes_auction(self):
        lot = self.make_auction(auction_buy_now_price=Decimal("2500.00"))
        result = bidding.buy_now(self.alice, lot.pk)
        self.assertEqual(result["status"], Listing.Status.COMPLETED)
        lot.refresh_from_db()
        self.assertEqual(lot.status, Listing.Status.COMPLETED)
        self.assertEqual(lot.auction_result, Listing.AuctionResult.SOLD)
        self.assertEqual(lot.winner, self.alice)
        self.assertEqual(lot.current_price, Decimal("2500.00"))
        self.assertEqual(AuctionBid.objects.filter(listing=lot, is_winning=True).count(), 1)

    def test_seller_cannot_buy_now(self):
        lot = self.make_auction(auction_buy_now_price=Decimal("2500.00"))
        with self.assertRaises(bidding.BidError) as ctx:
            bidding.buy_now(self.owner, lot.pk)
        self.assertEqual(ctx.exception.code, "seller_cannot_bid")

    def test_buy_now_api_success(self):
        lot = self.make_auction(auction_buy_now_price=Decimal("2500.00"))
        client = Client()
        client.force_login(self.bob)
        resp = client.post(reverse("market_api_auction_buy_now", args=[lot.pk]))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()["ok"])
        lot.refresh_from_db()
        self.assertEqual(lot.winner, self.bob)
