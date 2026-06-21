"""Covers validation logic for the translated market Django models."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import ArchiveFile, Profile, Rubric

from ..models import Bid, Listing


class ListingModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="pass123")
        self.profile = Profile.objects.create(user=self.owner, terms_version_accepted=settings.TERMS_VERSION)
        self.rubric = Rubric.objects.create(
            profile=self.profile,
            name="Картины",
            slug="kartiny",
            is_text_mode=False,
            field_schema=[],
        )
        self.file = ArchiveFile.objects.create(rubric=self.rubric, title="Пейзаж", data={})

    def test_shop_requires_positive_price(self):
        listing = Listing(
            item=self.file,
            seller=self.owner,
            type=Listing.Type.SHOP,
            category=Listing.Category.COLLECTING,
        )
        with self.assertRaises(ValidationError) as exc:
            listing.full_clean()
        self.assertIn("price", exc.exception.message_dict)

        listing.price = Decimal("5000.00")
        listing.full_clean()  # should not raise

    def test_category_is_required(self):
        listing = Listing(
            item=self.file,
            seller=self.owner,
            type=Listing.Type.SHOP,
            price=Decimal("100.00"),
        )
        with self.assertRaises(ValidationError) as exc:
            listing.full_clean()
        self.assertIn("category", exc.exception.message_dict)

    def test_free_forces_price_null(self):
        listing = Listing(
            item=self.file,
            seller=self.owner,
            type=Listing.Type.FREE,
            price=Decimal("10"),
            category=Listing.Category.COLLECTING,
        )
        with self.assertRaises(ValidationError):
            listing.full_clean()
        listing.price = None
        listing.full_clean()
        listing.save()
        self.assertIsNone(listing.price)

    def test_swap_requires_wishlist(self):
        listing = Listing(
            item=self.file,
            seller=self.owner,
            type=Listing.Type.SWAP,
            category=Listing.Category.COLLECTING,
        )
        with self.assertRaises(ValidationError) as exc:
            listing.full_clean()
        self.assertIn("swap_wishlist", exc.exception.message_dict)
        listing.swap_wishlist = "На обмен интересуют книги"
        listing.full_clean()

    def test_auction_requires_fields_and_sets_current_price(self):
        listing = Listing(
            item=self.file,
            seller=self.owner,
            type=Listing.Type.AUCTION,
            category=Listing.Category.COLLECTING,
        )
        with self.assertRaises(ValidationError):
            listing.full_clean()

        start = timezone.now() + timedelta(hours=1)
        end = start + timedelta(hours=2)
        listing.auction_start = start
        listing.auction_end = end
        listing.auction_start_price = Decimal("100.00")
        listing.auction_min_price = Decimal("150.00")
        listing.auction_step = Decimal("10.00")
        listing.full_clean()
        listing.save()
        self.assertEqual(listing.current_price, Decimal("100.00"))


class BidModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="pass123")
        self.bidder = User.objects.create_user(username="bidder", password="pass123")
        profile = Profile.objects.create(user=self.owner, terms_version_accepted=settings.TERMS_VERSION)
        rubric = Rubric.objects.create(
            profile=profile,
            name="Картины",
            slug="kartiny",
            is_text_mode=False,
            field_schema=[],
        )
        file = ArchiveFile.objects.create(rubric=rubric, title="Пейзаж", data={})
        now = timezone.now()
        self.listing = Listing.objects.create(
            item=file,
            seller=self.owner,
            type=Listing.Type.AUCTION,
            category=Listing.Category.COLLECTING,
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=2),
            auction_start_price=Decimal("100.00"),
            auction_min_price=Decimal("150.00"),
            auction_step=Decimal("10.00"),
        )

    def test_bid_must_meet_step(self):
        bid = Bid(listing=self.listing, bidder=self.bidder, amount=Decimal("5.00"))
        with self.assertRaises(ValidationError) as exc:
            bid.full_clean()
        self.assertIn("amount", exc.exception.message_dict)

        bid.amount = Decimal("10.00")
        bid.full_clean()
        bid.save()

    def test_bid_disallowed_for_seller(self):
        bid = Bid(listing=self.listing, bidder=self.owner, amount=Decimal("120.00"))
        with self.assertRaises(ValidationError) as exc:
            bid.full_clean()
        self.assertIn("amount", exc.exception.message_dict)
