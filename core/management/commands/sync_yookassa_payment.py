from django.core.management.base import BaseCommand, CommandError

from core.services import subscriptions


class Command(BaseCommand):
    help = 'Fetch a YooKassa payment by id and activate the matching subscription when it is paid.'

    def add_arguments(self, parser):
        parser.add_argument('payment_id', help='YooKassa payment id, for example 2f8f...')

    def handle(self, *args, **options):
        payment_id = str(options['payment_id']).strip()
        if not payment_id:
            raise CommandError('payment_id is required')

        try:
            result = subscriptions.process_yookassa_payment(payment_id)
        except subscriptions.PaymentUnavailable as exc:
            raise CommandError('YooKassa is not configured or the SDK is unavailable.') from exc
        except subscriptions.PaymentGatewayError as exc:
            raise CommandError('Could not fetch payment from YooKassa.') from exc

        if result.payment is None:
            raise CommandError(result.message or 'Local payment was not found.')

        self.stdout.write(
            self.style.SUCCESS(
                'payment_uuid={uuid} status={status} activated={activated} tariff={tariff} user_id={user_id}'.format(
                    uuid=result.payment.internal_uuid,
                    status=result.status,
                    activated=result.activated,
                    tariff=result.payment.tariff.code,
                    user_id=result.payment.user_id,
                )
            )
        )
