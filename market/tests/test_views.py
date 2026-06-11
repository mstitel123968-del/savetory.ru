from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ArchiveFile, Profile, Rubric

from ..models import Listing


class MarketViewsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="viewer", password="pass123")
        profile = Profile.objects.create(user=self.user, terms_version_accepted=settings.TERMS_VERSION)
        self.rubric = Rubric.objects.create(
            profile=profile,
            name="Картины",
            slug="kartiny",
            is_text_mode=False,
            field_schema=[],
        )
        self.file = ArchiveFile.objects.create(rubric=self.rubric, title="Пейзаж", data={})
        self.client = Client()

    def test_market_root_ok(self):
        response = self.client.get(reverse('market_root'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].endswith(reverse('market_auction')))

    def test_market_auction_category_filter(self):
        now = timezone.now()
        listing_auto = Listing.objects.create(
            item=self.file,
            seller=self.user,
            type=Listing.Type.AUCTION,
            category=Listing.Category.AUTO,
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=2),
            auction_start_price=Decimal('100.00'),
            auction_min_price=Decimal('150.00'),
            auction_step=Decimal('10.00'),
        )
        listing_hobby = Listing.objects.create(
            item=self.file,
            seller=self.user,
            type=Listing.Type.AUCTION,
            category=Listing.Category.HOBBY,
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=2),
            auction_start_price=Decimal('200.00'),
            auction_min_price=Decimal('250.00'),
            auction_step=Decimal('10.00'),
        )

        response = self.client.get(reverse('market_auction_by_cat', args=[Listing.Category.AUTO]))
        self.assertEqual(response.status_code, 200)
        page_obj = response.context['page_obj']
        self.assertIn(listing_auto, page_obj.object_list)
        self.assertNotIn(listing_hobby, page_obj.object_list)
