"""Server-side checks for the «Аукцион» create/bid/buy/edit API flows.

Page rendering is verified separately (see the manual render check in the task
summary); the bundled test client cannot capture template context on the local
Python 3.14 runtime, so these tests exercise the JSON endpoints and ORM rules.
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ArchiveFile, Profile, Rubric
from market.models import Listing

from .. import services
from ..models import AuctionLot


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


class AuctionUIFlowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.seller = User.objects.create_user(username="seller", password="pass123")
        self.buyer = User.objects.create_user(username="buyer", password="pass123")
        for u in (self.seller, self.buyer):
            Profile.objects.get_or_create(user=u)
            Profile.objects.filter(user=u).update(terms_version_accepted=django_settings.TERMS_VERSION)
        self.now = timezone.now()

    def _new_card_payload(self, mode, **over):
        payload = {
            "mode": mode,
            "title": over.pop("title", "Монета 1900"),
            "data": {"description": "старинная", "condition": "good", "location": "Москва"},
            "category": Listing.Category.COLLECTING,
            "start_price": "100",
            "min_bid_step": "10",
            "start_at": _iso(self.now - timedelta(hours=1)),
            "end_at": _iso(self.now + timedelta(hours=3)),
        }
        payload.update(over)
        return payload

    def _make_lot(self, **over):
        params = dict(
            title=over.pop("title", "Лот"), data=over.pop("data", {"description": "x"}),
            category=Listing.Category.COLLECTING, start_price=Decimal("100"),
            min_bid_step=Decimal("10"), start_at=self.now - timedelta(hours=1),
            end_at=self.now + timedelta(hours=3),
        )
        params.update(over)
        return services.create_card_in_auction(self.seller, **params)

    # -- access ---------------------------------------------------------------
    def test_create_page_requires_login(self):
        resp = self.client.get(reverse("market_auction_create"))
        self.assertEqual(resp.status_code, 302)

    def test_available_cards_excludes_active_lot_cards(self):
        self.client.force_login(self.seller)
        lot = self._make_lot(title="Занятая")
        profile = Profile.objects.get(user=self.seller)
        rub = Rubric.objects.create(profile=profile, name="Личное", slug="lichnoe")
        free = ArchiveFile(rubric=rub, owner=self.seller, title="Свободная", data={"d": "1"})
        free.save()
        resp = self.client.get(reverse("auction:available-cards"))
        ids = [c["id"] for c in resp.json()["cards"]]
        self.assertIn(free.pk, ids)
        self.assertNotIn(lot.card.pk, ids)

    # -- create modes ---------------------------------------------------------
    def test_publish_new_card_creates_active_lot_in_system_rubric(self):
        self.client.force_login(self.seller)
        resp = self.client.post(reverse("auction:lot-create"),
                                data=json.dumps(self._new_card_payload("publish")),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        lot = AuctionLot.objects.get(pk=resp.json()["lot"]["lot_id"])
        self.assertEqual(lot.status, AuctionLot.Status.ACTIVE)
        self.assertTrue(services.is_auction_rubric(lot.card.rubric))

    def test_draft_mode_hidden_and_inactive(self):
        self.client.force_login(self.seller)
        resp = self.client.post(reverse("auction:lot-create"),
                                data=json.dumps(self._new_card_payload("draft", title="Черновой")),
                                content_type="application/json")
        lot = AuctionLot.objects.get(pk=resp.json()["lot"]["lot_id"])
        self.assertEqual(lot.status, AuctionLot.Status.DRAFT)
        self.assertFalse(lot.listing.is_active)
        # Excluded from the public board queryset (drafts hidden).
        visible = Listing.objects.filter(type=Listing.Type.AUCTION).exclude(
            auction_lot__status__in=["draft", "cancelled"])
        self.assertNotIn(lot.listing_id, visible.values_list("id", flat=True))

    def test_schedule_mode_sets_scheduled(self):
        self.client.force_login(self.seller)
        payload = self._new_card_payload("schedule", title="Будущий",
                                         start_at=_iso(self.now + timedelta(hours=1)),
                                         end_at=_iso(self.now + timedelta(hours=5)))
        resp = self.client.post(reverse("auction:lot-create"),
                                data=json.dumps(payload), content_type="application/json")
        lot = AuctionLot.objects.get(pk=resp.json()["lot"]["lot_id"])
        self.assertEqual(lot.status, AuctionLot.Status.SCHEDULED)

    def test_create_from_archive_card(self):
        self.client.force_login(self.seller)
        profile = Profile.objects.get(user=self.seller)
        rub = Rubric.objects.create(profile=profile, name="Личное", slug="lichnoe")
        card = ArchiveFile(rubric=rub, owner=self.seller, title="Часы", data={"description": "наручные"})
        card.save()
        payload = {"file_id": card.pk, "mode": "publish", "category": Listing.Category.COLLECTING,
                   "start_price": "50", "min_bid_step": "5",
                   "start_at": _iso(self.now - timedelta(hours=1)),
                   "end_at": _iso(self.now + timedelta(hours=2))}
        resp = self.client.post(reverse("auction:lot-create-from-card"),
                                data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        card.refresh_from_db()
        self.assertEqual(card.rubric_id, rub.pk)  # source card stays put

    def test_condition_filter_at_orm_level(self):
        self._make_lot(title="Новьё", data={"condition": "new"})
        self._make_lot(title="Бэушка", data={"condition": "used"})
        new_only = Listing.objects.filter(type=Listing.Type.AUCTION, item__data__condition="new")
        titles = [l.item.title for l in new_only]
        self.assertIn("Новьё", titles)
        self.assertNotIn("Бэушка", titles)

    # -- bid / buy-now / edit -------------------------------------------------
    def test_bid_buy_now_and_edit_flow(self):
        lot = self._make_lot(title="Торги", buy_now_price=Decimal("500"))

        self.client.force_login(self.seller)
        edit = self.client.post(reverse("auction:lot-edit", args=[lot.pk]),
                                data=json.dumps({"description": "обновлено", "start_price": "120"}),
                                content_type="application/json")
        self.assertEqual(edit.status_code, 200, edit.content)

        bid_self = self.client.post(reverse("auction:lot-bid", args=[lot.pk]),
                                    data=json.dumps({"amount": "200"}), content_type="application/json")
        self.assertEqual(bid_self.status_code, 400)  # cannot bid on own lot

        self.client.force_login(self.buyer)
        bid = self.client.post(reverse("auction:lot-bid", args=[lot.pk]),
                               data=json.dumps({"amount": "200"}), content_type="application/json")
        self.assertEqual(bid.status_code, 200, bid.content)
        lot.refresh_from_db()
        self.assertEqual(lot.current_price, Decimal("200"))

        self.client.force_login(self.seller)
        edit2 = self.client.post(reverse("auction:lot-edit", args=[lot.pk]),
                                 data=json.dumps({"description": "поздно"}),
                                 content_type="application/json")
        self.assertEqual(edit2.status_code, 400)  # frozen after first bid

        self.client.force_login(self.buyer)
        buy = self.client.post(reverse("auction:lot-buy-now", args=[lot.pk]),
                               data=json.dumps({}), content_type="application/json")
        self.assertEqual(buy.status_code, 200, buy.content)
        lot.refresh_from_db()
        self.assertEqual(lot.status, AuctionLot.Status.SOLD)
        self.assertEqual(lot.winner_id, self.buyer.id)
