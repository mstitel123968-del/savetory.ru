"""Finalize auctions whose end time has passed.

Safe to run repeatedly (idempotent) — the completion service skips lots that are
already completed or cancelled. Intended for cron / a scheduler; no Celery.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from market.models import Listing
from market.services import bidding


class Command(BaseCommand):
    help = "Finalize active/scheduled auctions whose end time has passed."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=200,
                            help="How many lots to process per batch.")

    def handle(self, *args, **options):
        batch_size = max(1, options["batch_size"])
        now = timezone.now()
        processed = 0

        while True:
            ids = list(
                Listing.objects.filter(
                    type=Listing.Type.AUCTION,
                    status__in=[Listing.Status.ACTIVE, Listing.Status.SCHEDULED],
                    auction_end__lte=now,
                )
                .order_by("auction_end")
                .values_list("pk", flat=True)[:batch_size]
            )
            if not ids:
                break
            for listing_id in ids:
                listing = bidding.finalize_auction(listing_id)
                if listing is not None and listing.status == Listing.Status.COMPLETED:
                    processed += 1
            if len(ids) < batch_size:
                break

        self.stdout.write(self.style.SUCCESS(f"Finalized {processed} auctions"))
