from django.core.management.base import BaseCommand

from core.services.subscriptions import expire_due_subscriptions


class Command(BaseCommand):
    help = 'Expire ended paid subscriptions and move users back to Free.'

    def handle(self, *args, **options):
        count = expire_due_subscriptions()
        self.stdout.write(self.style.SUCCESS(f'Expired subscriptions: {count}'))
