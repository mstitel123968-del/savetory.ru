"""Tests the JSON endpoints that replace the Java market REST layer."""
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

from ..models import Listing


class MarketApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="pass123")
        self.other = User.objects.create_user(username="buyer", password="pass123")
        self.owner_profile = Profile.objects.create(user=self.owner, terms_version_accepted=settings.TERMS_VERSION)
        self.other_profile = Profile.objects.create(user=self.other, terms_version_accepted=settings.TERMS_VERSION)
        self.rubric = Rubric.objects.create(
            profile=self.owner_profile,
            name="Картины",
            slug="kartiny",
            is_text_mode=False,
            field_schema=[],
        )
        self.file = ArchiveFile.objects.create(rubric=self.rubric, title="Пейзаж", data={})
        self.client = Client()
        self.client.force_login(self.owner)

    def test_create_shop_listing(self):
        response = self.client.post(
            reverse('market_api_create'),
            data=json.dumps({
                'file_id': self.file.pk,
                'type': Listing.Type.SHOP,
                'price': '2500.50',
                'category': Listing.Category.COLLECTING,
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        listing = Listing.objects.get(pk=data['listing_id'])
        self.assertEqual(listing.type, Listing.Type.SHOP)
        self.assertEqual(listing.price, Decimal('2500.50'))
        self.assertEqual(listing.category, Listing.Category.COLLECTING)

    def test_create_listing_for_foreign_file_forbidden(self):
        foreign_rubric = Rubric.objects.create(
            profile=self.other_profile,
            name='Скульптуры',
            slug='sculpt',
            is_text_mode=False,
            field_schema=[],
        )
        foreign_file = ArchiveFile.objects.create(rubric=foreign_rubric, title='Статуя', data={})
        response = self.client.post(
            reverse('market_api_create'),
            data=json.dumps({
                'file_id': foreign_file.pk,
                'type': Listing.Type.FREE,
                'category': Listing.Category.COLLECTING,
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Listing.objects.filter(item=foreign_file).exists())

    def test_create_listing_requires_category(self):
        response = self.client.post(
            reverse('market_api_create'),
            data=json.dumps({
                'file_id': self.file.pk,
                'type': Listing.Type.SHOP,
                'price': '1000',
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn('category', data.get('errors', {}))

    def test_bid_api_updates_current_price(self):
        now = timezone.now()
        listing = Listing.objects.create(
            item=self.file,
            seller=self.owner,
            type=Listing.Type.AUCTION,
            category=Listing.Category.COLLECTING,
            auction_start=now - timedelta(hours=1),
            auction_end=now + timedelta(hours=2),
            auction_start_price=Decimal('100.00'),
            auction_min_price=Decimal('120.00'),
            auction_step=Decimal('10.00'),
        )
        bidder_client = Client()
        bidder_client.force_login(self.other)
        response = bidder_client.post(
            reverse('market_api_bid'),
            data=json.dumps({
                'listing_id': listing.pk,
                'amount': '10.00',
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        listing.refresh_from_db()
        self.assertEqual(listing.current_price, Decimal('110.00'))

        # Seller cannot bid on own listing
        response = self.client.post(
            reverse('market_api_bid'),
            data=json.dumps({
                'listing_id': listing.pk,
                'amount': '30.00',
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('errors', response.json())
