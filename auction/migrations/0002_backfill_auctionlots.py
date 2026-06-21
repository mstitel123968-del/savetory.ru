"""Backfill an AuctionLot extension for every pre-existing auction Listing.

The legacy auction parameters lived inline on ``market.Listing``
(auction_start/auction_end/auction_start_price/auction_step/current_price).
After introducing :class:`auction.AuctionLot` as a one-to-one extension, this
migration creates a matching lot for each existing ``Listing(type=auction)``
that does not have one yet, copying those values across.
"""

from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def _status_for(listing, now):
    if not listing.is_active:
        return 'ended'
    if listing.auction_start and now < listing.auction_start:
        return 'scheduled'
    if listing.auction_end and now >= listing.auction_end:
        return 'ended'
    return 'active'


def backfill_lots(apps, schema_editor):
    Listing = apps.get_model('market', 'Listing')
    AuctionLot = apps.get_model('auction', 'AuctionLot')
    now = timezone.now()

    for listing in Listing.objects.filter(type='auction', auction_lot__isnull=True):
        start_price = listing.auction_start_price or listing.current_price or Decimal('0.01')
        current_price = listing.current_price or start_price
        step = listing.auction_step or Decimal('1.00')
        AuctionLot.objects.create(
            listing=listing,
            status=_status_for(listing, now),
            start_price=start_price,
            current_price=current_price,
            min_bid_step=step,
            start_at=listing.auction_start,
            end_at=listing.auction_end,
        )


def remove_lots(apps, schema_editor):
    # Reversing simply drops the backfilled lots; the inline Listing fields
    # remain the source of truth on the way down.
    AuctionLot = apps.get_model('auction', 'AuctionLot')
    AuctionLot.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('auction', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_lots, remove_lots),
    ]
