"""View tests for the public auction lot detail page."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.test import client as test_client
from django.urls import reverse
from django.utils import timezone

from core.models import ArchiveFile, Profile, Rubric

from ..models import Listing, ListingImage
from ..services import bidding


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AuctionDetailViewTests(TestCase):
    def setUp(self):
        # Scope a no-op around the test client's template-context capture: it
        # only disables response.context (unused here) and avoids a Python 3.14
        # incompatibility when rendering templates in tests.
        self._orig_store = test_client.store_rendered_templates
        test_client.store_rendered_templates = lambda store, **kwargs: None

        User = get_user_model()
        self.owner = User.objects.create_user(username="seller", password="pass123")
        self.bidder = User.objects.create_user(username="bob", password="pass123")
        for user in (self.owner, self.bidder):
            Profile.objects.create(user=user, terms_version_accepted=settings.TERMS_VERSION)
        self.rubric = Rubric.objects.create(profile=self.owner.profile, name="Картины", slug="kartiny",
                                             is_text_mode=False, field_schema=[])
        self.card = ArchiveFile.objects.create(rubric=self.rubric, title="Старинная ваза", data={})
        self.now = timezone.now()

    def tearDown(self):
        test_client.store_rendered_templates = self._orig_store

    def make_lot(self, **over):
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
        return lot

    def url(self, lot):
        return reverse("market_auction_detail", args=[lot.pk])

    # -- access ---------------------------------------------------------------
    def test_public_view_of_published_lot(self):
        lot = self.make_lot()
        resp = Client().get(self.url(lot))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Старинная ваза")
        self.assertContains(resp, "Аукцион идёт")

    def test_draft_hidden_from_guest(self):
        lot = self.make_lot(status=Listing.Status.DRAFT, is_active=False)
        self.assertEqual(Client().get(self.url(lot)).status_code, 404)

    def test_draft_hidden_from_other_user(self):
        lot = self.make_lot(status=Listing.Status.DRAFT, is_active=False)
        client = Client()
        client.force_login(self.bidder)
        self.assertEqual(client.get(self.url(lot)).status_code, 404)

    def test_draft_visible_to_owner(self):
        lot = self.make_lot(status=Listing.Status.DRAFT, is_active=False)
        client = Client()
        client.force_login(self.owner)
        self.assertEqual(client.get(self.url(lot)).status_code, 200)

    # -- statuses -------------------------------------------------------------
    def test_status_texts(self):
        cases = {
            Listing.Status.SCHEDULED: "Аукцион начнётся",
            Listing.Status.COMPLETED: "Аукцион завершён",
            Listing.Status.CANCELLED: "Аукцион отменён",
        }
        for status, text in cases.items():
            lot = self.make_lot(status=status, is_active=status == Listing.Status.SCHEDULED,
                                auction_start=self.now + timedelta(hours=1) if status == Listing.Status.SCHEDULED else self.now - timedelta(hours=2),
                                auction_end=self.now + timedelta(hours=3) if status == Listing.Status.SCHEDULED else self.now - timedelta(minutes=1))
            resp = Client().get(self.url(lot))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, text)

    # -- price / reserve ------------------------------------------------------
    def test_start_price_shown_before_bids(self):
        lot = self.make_lot()
        resp = Client().get(self.url(lot))
        self.assertContains(resp, "Стартовая цена")
        self.assertContains(resp, "1000.00")

    def test_current_price_shown_after_bids(self):
        lot = self.make_lot()
        bidding.place_bid(self.bidder, lot.pk, Decimal("200.00"))
        resp = Client().get(self.url(lot))
        self.assertContains(resp, "Текущая цена")
        self.assertContains(resp, "1200.00")

    def test_reserve_amount_not_in_html(self):
        lot = self.make_lot(auction_reserve_price=Decimal("1500.00"))
        resp = Client().get(self.url(lot))
        content = resp.content.decode("utf-8")
        self.assertNotIn("1500", content)
        self.assertIn("Резерв пока не достигнут", content)

    def test_seller_sees_management_block(self):
        lot = self.make_lot()
        client = Client()
        client.force_login(self.owner)
        resp = client.get(self.url(lot))
        self.assertContains(resp, "Управление аукционом")
