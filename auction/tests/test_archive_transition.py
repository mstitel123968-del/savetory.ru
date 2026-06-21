"""Covers «Ваш архив → Маркет → Аукцион»: per-card, owner- and status-aware
availability, draft editing, re-listing, and attribute isolation."""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ArchiveFile, Profile, Rubric
from market.models import Listing

from .. import services
from ..models import AuctionLot


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


class ArchiveToAuctionTransitionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("owner", password="pass123")
        self.other = User.objects.create_user("other", password="pass123")
        for u in (self.owner, self.other):
            Profile.objects.get_or_create(user=u)
            Profile.objects.filter(user=u).update(terms_version_accepted=django_settings.TERMS_VERSION)
        self.now = timezone.now()
        self.rubric = Rubric.objects.create(
            profile=Profile.objects.get(user=self.owner), name="Личное", slug="lichnoe")

    def _card(self, title="Ваза", data=None):
        card = ArchiveFile(rubric=self.rubric, owner=self.owner, title=title,
                           data=data if data is not None else {"description": "фарфор"})
        card.save()
        return card

    def _publish(self, card, mode="publish", **over):
        params = dict(category=Listing.Category.COLLECTING, start_price=Decimal("100"),
                      min_bid_step=Decimal("10"), start_at=self.now - timedelta(hours=1),
                      end_at=self.now + timedelta(hours=3), mode=mode)
        params.update(over)
        return services.publish_lot_from_card(self.owner, card, **params)

    # 1. No lot -> creation allowed.
    def test_decision_create_when_no_lot(self):
        state = services.serialize_card_auction_state(self._card(), self.owner)
        self.assertEqual(state["decision"], "create")
        self.assertFalse(state["has_lot"])

    # 2. Draft exists -> edit it (prefill present), no duplicate allowed.
    def test_draft_yields_edit_decision_and_blocks_second_lot(self):
        card = self._card("Монета")
        lot = self._publish(card, mode="draft")
        self.assertEqual(lot.status, AuctionLot.Status.DRAFT)

        state = services.serialize_card_auction_state(card, self.owner)
        self.assertEqual(state["decision"], "edit")
        self.assertEqual(state["draft"]["lot_id"], lot.pk)
        self.assertEqual(state["draft"]["start_price"], "100.00")

        with self.assertRaises(ValidationError):  # second lot blocked while unfinished
            self._publish(card, mode="publish")

    # 3. Publishing a draft via edit makes it active (-> then blocked).
    def test_publish_draft_via_edit(self):
        card = self._card("Часы")
        lot = self._publish(card, mode="draft")
        services.edit_lot_before_bids(self.owner, lot, mode="publish",
                                      start_price=Decimal("120"))
        lot.refresh_from_db()
        self.assertEqual(lot.status, AuctionLot.Status.ACTIVE)
        self.assertTrue(lot.listing.is_active)
        self.assertEqual(services.serialize_card_auction_state(card, self.owner)["decision"], "blocked")

    # 4. Active/scheduled lot -> blocked.
    def test_active_lot_is_blocked(self):
        card = self._card("Картина")
        self._publish(card, mode="publish")
        self.assertEqual(services.serialize_card_auction_state(card, self.owner)["decision"], "blocked")

    # 5. Finished lots (ended/cancelled) allow re-listing.
    def test_ended_lot_allows_relist(self):
        card = self._card("Лампа")
        lot = self._publish(card, mode="publish")
        services.finalize_ended(lot)
        self.assertEqual(services.serialize_card_auction_state(card, self.owner)["decision"], "create")
        new_lot = self._publish(card, mode="publish")  # re-list succeeds
        self.assertNotEqual(new_lot.pk, lot.pk)

    def test_cancelled_lot_allows_relist(self):
        card = self._card("Стол")
        lot = self._publish(card, mode="publish")
        services.cancel_lot(lot)
        self.assertEqual(services.serialize_card_auction_state(card, self.owner)["decision"], "create")

    # 6. One lot must not block the user's other cards.
    def test_other_cards_not_blocked_by_one_lot(self):
        busy = self._card("Занятая")
        self._publish(busy, mode="publish")
        free = self._card("Свободная")
        self.assertEqual(services.serialize_card_auction_state(free, self.owner)["decision"], "create")

    # 7. Owner enforced server-side: ID spoofing rejected.
    def test_stranger_cannot_publish_via_id_spoof(self):
        card = self._card("Чужое")
        self.client.force_login(self.other)
        payload = {"file_id": card.pk, "mode": "publish", "category": Listing.Category.COLLECTING,
                   "start_price": "50", "min_bid_step": "5",
                   "start_at": _iso(self.now - timedelta(hours=1)),
                   "end_at": _iso(self.now + timedelta(hours=2))}
        resp = self.client.post(reverse("auction:lot-create-from-card"),
                                data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 404)  # not found for non-owner
        self.assertFalse(AuctionLot.objects.filter(listing__item=card).exists())

    # 8. Card created inside the auction lands in the system rubric.
    def test_in_auction_card_in_system_rubric(self):
        lot = services.create_card_in_auction(
            self.owner, title="Внутри аукциона", data={"description": "x"},
            category=Listing.Category.COLLECTING, start_price=Decimal("10"),
            min_bid_step=Decimal("1"), start_at=self.now - timedelta(hours=1),
            end_at=self.now + timedelta(hours=2))
        self.assertTrue(services.is_auction_rubric(lot.card.rubric))

    # 9. A normal card is NOT copied into the system rubric.
    def test_normal_card_not_copied_to_system_rubric(self):
        card = self._card("Не копировать")
        self._publish(card, mode="publish")
        card.refresh_from_db()
        self.assertEqual(card.rubric_id, self.rubric.pk)
        system = services.get_or_create_auction_rubric(self.owner)
        self.assertFalse(ArchiveFile.objects.filter(rubric=system, title="Не копировать").exists())

    # 10. Auction attributes are stored on the lot snapshot, never on the card.
    def test_attributes_stored_on_snapshot_not_card(self):
        self.client.force_login(self.owner)
        card = self._card("Сумка", data={"description": "кожа"})
        payload = {"file_id": card.pk, "mode": "draft", "category": Listing.Category.FASHION,
                   "start_price": "200", "min_bid_step": "10",
                   "condition": "good", "completeness": "полный комплект",
                   "start_at": _iso(self.now - timedelta(hours=1)),
                   "end_at": _iso(self.now + timedelta(hours=4))}
        resp = self.client.post(reverse("auction:lot-create-from-card"),
                                data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200, resp.content)
        lot = AuctionLot.objects.get(pk=resp.json()["lot"]["lot_id"])
        self.assertEqual(lot.snapshot["data"]["condition"], "good")
        self.assertEqual(lot.snapshot["data"]["completeness"], "полный комплект")
        card.refresh_from_db()
        self.assertNotIn("condition", card.data)  # card structure untouched

    # 11. Status endpoint exposes the decision for the UI.
    def test_card_status_endpoint_returns_decision(self):
        self.client.force_login(self.owner)
        card = self._card("Статус")
        self._publish(card, mode="draft")
        resp = self.client.get(reverse("auction:card-status", args=[card.pk]),
                               HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"]["decision"], "edit")
