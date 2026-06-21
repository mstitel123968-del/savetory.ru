"""Model-level tests for the auction lot data model (status, item details,
delivery, reserve price, auto-extend, ListingImage and the reserve rename
migration)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from core.models import ArchiveFile, ArchiveFileImage, Profile, Rubric

from ..models import Listing, ListingImage


def _make_owner_and_file(username="owner"):
    User = get_user_model()
    user = User.objects.create_user(username=username, password="pass123")
    profile = Profile.objects.create(user=user, terms_version_accepted=settings.TERMS_VERSION)
    rubric = Rubric.objects.create(profile=profile, name="Картины", slug="kartiny", is_text_mode=False, field_schema=[])
    archive = ArchiveFile.objects.create(rubric=rubric, title="Пейзаж", data={})
    return user, archive


class ListingStatusValidationTests(TestCase):
    def setUp(self):
        self.owner, self.file = _make_owner_and_file()
        self.now = timezone.now()

    def _auction(self, **over):
        params = dict(item=self.file, seller=self.owner, type=Listing.Type.AUCTION, category=Listing.Category.COLLECTING)
        params.update(over)
        return Listing(**params)

    def test_draft_allows_partial_auction_fields(self):
        listing = self._auction(is_active=False, auction_start_price=Decimal("100.00"))
        listing.full_clean()  # must not raise — draft permits empty auction fields
        self.assertEqual(listing.status, Listing.Status.DRAFT)
        self.assertFalse(listing.is_active)

    def test_active_requires_full_fields(self):
        listing = self._auction()  # is_active default True -> status active
        with self.assertRaises(ValidationError) as exc:
            listing.full_clean()
        self.assertIn("auction_start", exc.exception.message_dict)
        self.assertEqual(listing.status, Listing.Status.ACTIVE)

    def test_scheduled_requires_full_fields(self):
        listing = self._auction(status=Listing.Status.SCHEDULED, is_active=True)
        with self.assertRaises(ValidationError) as exc:
            listing.full_clean()
        self.assertIn("auction_start_price", exc.exception.message_dict)
        # Fill required fields -> valid and stays scheduled.
        listing.auction_start = self.now + timedelta(hours=1)
        listing.auction_end = self.now + timedelta(hours=3)
        listing.auction_start_price = Decimal("100.00")
        listing.auction_step = Decimal("10.00")
        listing.full_clean()
        self.assertEqual(listing.status, Listing.Status.SCHEDULED)

    def test_condition_choices(self):
        for value in (c.value for c in Listing.Condition):
            listing = Listing(item=self.file, seller=self.owner, type=Listing.Type.SHOP,
                              category=Listing.Category.COLLECTING, price=Decimal("100"), item_condition=value)
            listing.full_clean()
        bad = Listing(item=self.file, seller=self.owner, type=Listing.Type.SHOP,
                      category=Listing.Category.COLLECTING, price=Decimal("100"), item_condition="mint")
        with self.assertRaises(ValidationError):
            bad.full_clean()

    def test_delivery_methods_allowed_and_unique(self):
        ok = Listing(item=self.file, seller=self.owner, type=Listing.Type.SHOP, category=Listing.Category.COLLECTING,
                     price=Decimal("100"), delivery_methods=["delivery", "pickup"])
        ok.full_clean()
        bad_value = Listing(item=self.file, seller=self.owner, type=Listing.Type.SHOP, category=Listing.Category.COLLECTING,
                            price=Decimal("100"), delivery_methods=["teleport"])
        with self.assertRaises(ValidationError) as exc:
            bad_value.full_clean()
        self.assertIn("delivery_methods", exc.exception.message_dict)
        dup = Listing(item=self.file, seller=self.owner, type=Listing.Type.SHOP, category=Listing.Category.COLLECTING,
                      price=Decimal("100"), delivery_methods=["delivery", "delivery"])
        with self.assertRaises(ValidationError):
            dup.full_clean()

    def test_delivery_cost_requires_delivery_and_nonnegative(self):
        no_delivery = Listing(item=self.file, seller=self.owner, type=Listing.Type.SHOP, category=Listing.Category.COLLECTING,
                              price=Decimal("100"), delivery_methods=["pickup"], delivery_cost=Decimal("300"))
        with self.assertRaises(ValidationError) as exc:
            no_delivery.full_clean()
        self.assertIn("delivery_cost", exc.exception.message_dict)

        negative = Listing(item=self.file, seller=self.owner, type=Listing.Type.SHOP, category=Listing.Category.COLLECTING,
                           price=Decimal("100"), delivery_methods=["delivery"], delivery_cost=Decimal("-5"))
        with self.assertRaises(ValidationError):
            negative.full_clean()

        ok = Listing(item=self.file, seller=self.owner, type=Listing.Type.SHOP, category=Listing.Category.COLLECTING,
                     price=Decimal("100"), delivery_methods=["delivery"], delivery_cost=Decimal("300"))
        ok.full_clean()

    def test_reserve_price_optional_and_not_below_start(self):
        base = dict(auction_start=self.now + timedelta(hours=1), auction_end=self.now + timedelta(hours=3),
                    auction_start_price=Decimal("100.00"), auction_step=Decimal("10.00"))
        # Optional: no reserve is fine.
        self._auction(**base).full_clean()
        # Below start -> error (via the auction_min_price alias too).
        low = self._auction(auction_reserve_price=Decimal("50.00"), **base)
        with self.assertRaises(ValidationError) as exc:
            low.full_clean()
        self.assertIn("auction_reserve_price", exc.exception.message_dict)
        # Equal/above start -> ok.
        self._auction(auction_reserve_price=Decimal("150.00"), **base).full_clean()

    def test_auction_min_price_alias_maps_to_reserve(self):
        listing = self._auction()
        listing.auction_min_price = Decimal("250.00")
        self.assertEqual(listing.auction_reserve_price, Decimal("250.00"))
        self.assertEqual(listing.auction_min_price, Decimal("250.00"))

    def test_auto_extend_range(self):
        base = dict(auction_start=self.now + timedelta(hours=1), auction_end=self.now + timedelta(hours=3),
                    auction_start_price=Decimal("100.00"), auction_step=Decimal("10.00"))
        for minutes in (1, 2, 30):
            self._auction(auction_auto_extend_minutes=minutes, **base).full_clean()
        for minutes in (0, 31):
            with self.assertRaises(ValidationError) as exc:
                self._auction(auction_auto_extend_minutes=minutes, **base).full_clean()
            self.assertIn("auction_auto_extend_minutes", exc.exception.message_dict)


class ListingImageTests(TestCase):
    def setUp(self):
        self.owner, self.file = _make_owner_and_file()
        self.listing = Listing.objects.create(item=self.file, seller=self.owner, type=Listing.Type.SHOP,
                                               category=Listing.Category.COLLECTING, price=Decimal("100"))

    def test_single_cover_per_lot(self):
        ListingImage.objects.create(listing=self.listing, is_cover=True, display_order=0)
        second = ListingImage(listing=self.listing, is_cover=True, display_order=1)
        with self.assertRaises(ValidationError) as exc:
            second.full_clean()
        self.assertIn("is_cover", exc.exception.message_dict)

    def test_display_order_non_negative(self):
        image = ListingImage(listing=self.listing, display_order=-1)
        with self.assertRaises(ValidationError) as exc:
            image.full_clean()
        self.assertIn("display_order", exc.exception.message_dict)

    def test_images_ordering(self):
        ListingImage.objects.create(listing=self.listing, display_order=2)
        ListingImage.objects.create(listing=self.listing, display_order=0)
        ListingImage.objects.create(listing=self.listing, display_order=1)
        orders = list(self.listing.images.values_list("display_order", flat=True))
        self.assertEqual(orders, [0, 1, 2])

    def test_duplicate_source_image_blocked(self):
        afi = ArchiveFileImage.objects.create(archive_file=self.file, image="archive/x.jpg", display_order=0)
        first = ListingImage(listing=self.listing, source_image=afi, display_order=0)
        first.full_clean()
        first.save()
        dup = ListingImage(listing=self.listing, source_image=afi, display_order=1)
        with self.assertRaises(ValidationError) as exc:
            dup.full_clean()
        self.assertIn("source_image", exc.exception.message_dict)

    def test_editing_or_deleting_lot_image_keeps_archive_image(self):
        afi = ArchiveFileImage.objects.create(archive_file=self.file, image="archive/y.jpg", display_order=0)
        lot_image = ListingImage.objects.create(listing=self.listing, source_image=afi, display_order=0)
        lot_image.display_order = 5
        lot_image.save()
        lot_image.delete()
        afi.refresh_from_db()
        self.assertTrue(ArchiveFileImage.objects.filter(pk=afi.pk).exists())
        self.assertEqual(afi.image.name, "archive/y.jpg")


class ReservePriceRenameMigrationTests(TransactionTestCase):
    """The auction_min_price -> auction_reserve_price rename keeps its data."""

    def test_reserve_price_preserved_through_rename(self):
        owner, archive = _make_owner_and_file("migowner")
        now = timezone.now()

        # Roll market back to the pre-rename state and insert a legacy row.
        MigrationExecutor(connection).migrate([("market", "0002_listing_category")])
        old_state = MigrationExecutor(connection).loader.project_state([("market", "0002_listing_category")])
        OldListing = old_state.apps.get_model("market", "Listing")
        old = OldListing.objects.create(
            item_id=archive.pk, seller_id=owner.pk, type="auction", category="collecting",
            auction_start=now, auction_end=now + timedelta(hours=2),
            auction_start_price=Decimal("100.00"), auction_min_price=Decimal("150.00"),
            auction_step=Decimal("10.00"),
        )
        try:
            # Apply the rename migration forward.
            MigrationExecutor(connection).migrate([("market", "0003_listing_auction_fields")])
            new_state = MigrationExecutor(connection).loader.project_state([("market", "0003_listing_auction_fields")])
            NewListing = new_state.apps.get_model("market", "Listing")
            migrated = NewListing.objects.get(pk=old.pk)
            self.assertEqual(migrated.auction_reserve_price, Decimal("150.00"))
            self.assertEqual(migrated.status, "active")
        finally:
            MigrationExecutor(connection).migrate([("market", "0003_listing_auction_fields")])
