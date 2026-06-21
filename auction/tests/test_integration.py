"""Covers the «Аукцион ↔ Ваш архив» backend integration."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import ArchiveFile, Profile, Rubric
from core.views import _card_active_lot_error
from market.models import Bid, Listing

from .. import services
from ..constants import AUCTION_FIELD_SCHEMA
from ..models import AuctionLot


class AuctionIntegrationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.seller = User.objects.create_user(username="seller", password="pass123")
        self.buyer = User.objects.create_user(username="buyer", password="pass123")
        self.now = timezone.now()

    def _publish(self, seller, **overrides):
        title = overrides.pop("title", "Лот")
        params = dict(
            category=Listing.Category.COLLECTING,
            start_price=Decimal("100"),
            min_bid_step=Decimal("10"),
            start_at=self.now - timedelta(hours=1),
            end_at=self.now + timedelta(hours=2),
        )
        params.update(overrides)
        return services.create_card_in_auction(seller, title=title,
                                                data={"description": "x"}, **params)

    def test_system_rubric_created_once(self):
        r1 = services.get_or_create_auction_rubric(self.seller)
        r2 = services.get_or_create_auction_rubric(self.seller)
        self.assertEqual(r1.pk, r2.pk)
        self.assertTrue(r1.is_system)
        self.assertEqual(r1.slug, "auction")
        self.assertEqual(len(r1.field_schema), len(AUCTION_FIELD_SCHEMA))
        self.assertEqual(Rubric.objects.filter(profile__user=self.seller, slug="auction").count(), 1)

    def test_card_in_auction_lands_in_system_rubric_with_snapshot(self):
        lot = self._publish(self.seller, title="Монета")
        rubric = services.get_or_create_auction_rubric(self.seller)
        self.assertEqual(lot.card.rubric_id, rubric.pk)
        self.assertEqual(lot.listing.type, Listing.Type.AUCTION)
        self.assertEqual(lot.status, AuctionLot.Status.ACTIVE)
        self.assertEqual(lot.snapshot.get("title"), "Монета")

    def test_publish_from_normal_card_keeps_source_in_place(self):
        profile, _ = Profile.objects.get_or_create(user=self.seller)
        normal = Rubric.objects.create(profile=profile, name="Личное", slug="lichnoe")
        card = ArchiveFile(rubric=normal, owner=self.seller, title="Часы", data={"d": "1"})
        card.save()
        lot = services.publish_lot_from_card(
            self.seller, card, category=Listing.Category.COLLECTING,
            start_price=Decimal("50"), min_bid_step=Decimal("5"),
            start_at=self.now - timedelta(hours=1), end_at=self.now + timedelta(hours=2),
        )
        card.refresh_from_db()
        self.assertEqual(card.rubric_id, normal.pk)  # not moved/copied
        self.assertEqual(lot.snapshot.get("title"), "Часы")

    def test_cannot_publish_someone_elses_card(self):
        lot = self._publish(self.seller, title="Чужое")
        with self.assertRaises(ValidationError):
            services.publish_lot_from_card(
                self.buyer, lot.card, category=Listing.Category.COLLECTING,
                start_price=Decimal("10"), min_bid_step=Decimal("1"),
                start_at=self.now - timedelta(hours=1), end_at=self.now + timedelta(hours=1),
            )

    def test_self_bid_blocked_buyer_bid_ok(self):
        lot = self._publish(self.seller, title="Ставки")
        with self.assertRaises(ValidationError):
            Bid(listing=lot.listing, bidder=self.seller, amount=Decimal("110")).save()
        Bid(listing=lot.listing, bidder=self.buyer, amount=Decimal("110")).save()
        self.assertEqual(lot.listing.bids.count(), 1)

    def test_active_lot_blocks_card_deletion(self):
        lot = self._publish(self.seller, title="Защита")
        msg = _card_active_lot_error(self.seller, str(lot.card.pk))
        self.assertIsNotNone(msg)
        self.assertIn("торг", msg.lower())

    def test_sold_writes_outcome_to_card_without_winner_pii(self):
        lot = self._publish(self.seller, title="Продажа")
        services.finalize_sold(lot, self.buyer, Decimal("150"))
        card = lot.card
        card.refresh_from_db()
        self.assertEqual(card.status, ArchiveFile.Status.SOLD)
        self.assertEqual(card.data["auction"]["final_price"], "150")
        self.assertEqual(card.data["auction"]["sale_status"], "sold")
        self.assertNotIn(self.buyer.username, str(card.data))
        # Winner identity is owner-only.
        self.assertFalse(services.serialize_card_auction_state(card, self.buyer).get("winner_visible"))
        self.assertTrue(services.serialize_card_auction_state(card, self.seller).get("winner_visible"))
        # Card is deletable again once the lot is no longer live.
        self.assertIsNone(_card_active_lot_error(self.seller, str(card.pk)))

    def test_relist_after_cancel_creates_new_lot_same_card(self):
        lot = self._publish(self.seller, title="Повтор")
        services.cancel_lot(lot)
        self.assertTrue(lot.can_relist())
        new_lot = services.relist_card(
            self.seller, lot,
            start_price=Decimal("120"), min_bid_step=Decimal("10"),
            start_at=self.now - timedelta(minutes=30), end_at=self.now + timedelta(hours=2),
        )
        self.assertNotEqual(new_lot.pk, lot.pk)
        self.assertEqual(new_lot.card.pk, lot.card.pk)


class SystemRubricImmutabilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="u", password="pass123")
        self.client.force_login(self.user)
        self.system = services.get_or_create_auction_rubric(self.user)
        # Avoid TermsAcceptanceMiddleware blocking API POSTs in tests.
        Profile.objects.filter(user=self.user).update(
            terms_version_accepted=django_settings.TERMS_VERSION
        )

    def test_cannot_create_rubric_named_auction(self):
        resp = self.client.post("/api/archive/rubrics/", {
            "name": "Аукцион", "slug": "moja", "field_schema": "[]",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["success"])

    def test_cannot_move_card_into_system_rubric(self):
        import json
        resp = self.client.post(
            "/api/archive/files/move/",
            data=json.dumps({
                "file_id": "x1", "source_rubric_id": "999",
                "target_rubric_id": str(self.system.pk),
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("target_rubric_id", resp.json()["errors"])
