import json
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import ArchiveFile, Profile, Rubric, SubscriptionPayment, SubscriptionPlan, UserSubscription
from core.services import subscriptions
from market.services import auction as market_auction
from market.models import Listing


class SubscriptionTests(TestCase):
    def setUp(self):
        subscriptions.seed_default_plans()
        self.user = User.objects.create_user(username='owner', password='pass123')
        self.profile, _ = Profile.objects.get_or_create(user=self.user)
        self.profile.terms_version_accepted = settings.TERMS_VERSION
        self.profile.save(update_fields=['terms_version_accepted'])
        self.rubric = Rubric.objects.create(
            profile=self.profile,
            name='Main',
            slug='main',
            field_schema=[],
        )

    def _card(self, title='Item'):
        return ArchiveFile.objects.create(
            rubric=self.rubric,
            owner=self.user,
            title=title,
            data={'title': title},
        )

    def _auction_listing(self, title='Lot'):
        card = self._card(title)
        now = timezone.now()
        return Listing.objects.create(
            item=card,
            seller=self.user,
            type=Listing.Type.AUCTION,
            status=Listing.Status.ACTIVE,
            category=Listing.Category.COLLECTING,
            title=title,
            item_condition=Listing.Condition.GOOD,
            location='Moscow',
            delivery_methods=[Listing.DeliveryMethod.PICKUP],
            auction_start=now - timedelta(minutes=5),
            auction_end=now + timedelta(days=1),
            auction_start_price=Decimal('100.00'),
            auction_step=Decimal('10.00'),
            current_price=Decimal('100.00'),
        )

    def _archive_state(self, count):
        return {
            'rubrics': [
                {
                    'id': 'r1',
                    'name': 'Main',
                    'files': [{'id': f'f{i}', 'title': f'Item {i}'} for i in range(count)],
                }
            ]
        }

    def test_free_subscription_is_assigned_automatically(self):
        subscription = subscriptions.get_active_subscription(self.user)

        self.assertEqual(subscription.plan.code, SubscriptionPlan.Code.FREE)
        self.assertEqual(subscription.status, UserSubscription.Status.ACTIVE)
        self.assertEqual(subscription.billing_period, UserSubscription.BillingPeriod.FREE)

    def test_paid_subscription_activation_replaces_free_plan(self):
        plus = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PLUS)

        subscription = subscriptions.activate_subscription(
            self.user,
            plus,
            billing_period=UserSubscription.BillingPeriod.MONTH,
            auto_renew=True,
        )

        self.assertEqual(subscription.plan, plus)
        self.assertEqual(subscription.status, UserSubscription.Status.ACTIVE)
        self.assertEqual(subscription.billing_period, UserSubscription.BillingPeriod.MONTH)
        self.assertTrue(subscription.auto_renew)
        self.assertEqual(subscription.last_successful_payment, subscription.starts_at)
        self.assertEqual(UserSubscription.objects.filter(user=self.user, status=UserSubscription.Status.ACTIVE).count(), 1)

    def test_paid_subscription_month_uses_calendar_period(self):
        plus = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PLUS)
        starts_at = timezone.make_aware(datetime(2026, 1, 31, 12, 0, 0))

        subscription = subscriptions.activate_subscription(
            self.user,
            plus,
            billing_period=UserSubscription.BillingPeriod.MONTH,
            starts_at=starts_at,
        )

        self.assertEqual(subscription.expires_at, timezone.make_aware(datetime(2026, 2, 28, 12, 0, 0)))

    def test_paid_subscription_year_uses_calendar_period(self):
        pro = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PRO)
        starts_at = timezone.make_aware(datetime(2024, 2, 29, 12, 0, 0))

        subscription = subscriptions.activate_subscription(
            self.user,
            pro,
            billing_period=UserSubscription.BillingPeriod.YEAR,
            starts_at=starts_at,
        )

        self.assertEqual(subscription.expires_at, timezone.make_aware(datetime(2025, 2, 28, 12, 0, 0)))

    def test_subscription_payment_is_created_for_paid_tariff(self):
        plus = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PLUS)

        payment = subscriptions.create_subscription_payment(
            self.user,
            plus,
            period=UserSubscription.BillingPeriod.MONTH,
        )

        self.assertEqual(payment.user, self.user)
        self.assertEqual(payment.tariff, plus)
        self.assertEqual(payment.period, SubscriptionPayment.Period.MONTH)
        self.assertEqual(payment.amount, Decimal('99.00'))
        self.assertEqual(payment.currency, 'RUB')
        self.assertEqual(payment.status, SubscriptionPayment.Status.CREATED)
        self.assertFalse(payment.subscription_activated)
        self.assertTrue(payment.idempotence_key)

    def test_paid_plan_prices_match_current_tariffs(self):
        plus = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PLUS)
        pro = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PRO)

        self.assertEqual(plus.monthly_price, Decimal('99.00'))
        self.assertEqual(plus.yearly_price, Decimal('990.00'))
        self.assertEqual(pro.monthly_price, Decimal('199.00'))
        self.assertEqual(pro.yearly_price, Decimal('1990.00'))

    def test_plus_allows_up_to_twenty_thousand_archive_objects(self):
        subscriptions.activate_subscription(
            self.user,
            SubscriptionPlan.Code.PLUS,
            billing_period=UserSubscription.BillingPeriod.MONTH,
        )

        self.assertTrue(subscriptions.can_create_archive_file(self.user, incoming_count=20000))
        subscriptions.assert_archive_state_within_limit(self.user, self._archive_state(20000), {'rubrics': []})

    def test_plus_blocks_twenty_thousand_first_archive_object(self):
        subscriptions.activate_subscription(
            self.user,
            SubscriptionPlan.Code.PLUS,
            billing_period=UserSubscription.BillingPeriod.MONTH,
        )

        with self.assertRaises(subscriptions.SubscriptionLimitError):
            subscriptions.assert_archive_state_within_limit(self.user, self._archive_state(20001), {'rubrics': []})

    def test_pro_archive_is_unlimited(self):
        subscriptions.activate_subscription(
            self.user,
            SubscriptionPlan.Code.PRO,
            billing_period=UserSubscription.BillingPeriod.YEAR,
        )

        self.assertTrue(subscriptions.can_create_archive_file(self.user, incoming_count=100000))
        subscriptions.assert_archive_state_within_limit(self.user, self._archive_state(50000), {'rubrics': []})
        limits = subscriptions.subscription_limits(self.user)
        self.assertIsNone(limits['archive_limit'])
        self.assertEqual(limits['archive_limit_label'], 'Без ограничений')

    def test_seeding_updates_plans_without_touching_user_subscriptions(self):
        subscriptions.activate_subscription(
            self.user,
            SubscriptionPlan.Code.PLUS,
            billing_period=UserSubscription.BillingPeriod.MONTH,
        )
        subscription_ids = set(UserSubscription.objects.filter(user=self.user).values_list('id', flat=True))

        subscriptions.seed_default_plans()
        subscriptions.seed_default_plans()

        self.assertEqual(
            subscription_ids,
            set(UserSubscription.objects.filter(user=self.user).values_list('id', flat=True)),
        )
        self.assertEqual(SubscriptionPlan.objects.filter(code=SubscriptionPlan.Code.PLUS).count(), 1)
        self.assertEqual(SubscriptionPlan.objects.filter(code=SubscriptionPlan.Code.PRO).count(), 1)

    def test_expired_paid_subscription_moves_account_to_free(self):
        plus = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PLUS)
        starts_at = timezone.now() - timedelta(days=31)
        paid = subscriptions.activate_subscription(
            self.user,
            plus,
            billing_period=UserSubscription.BillingPeriod.MONTH,
            starts_at=starts_at,
        )

        subscriptions.expire_due_subscriptions(now=timezone.now())

        paid.refresh_from_db()
        active = subscriptions.get_active_subscription(self.user, refresh=False)
        self.assertEqual(paid.status, UserSubscription.Status.EXPIRED)
        self.assertEqual(active.plan.code, SubscriptionPlan.Code.FREE)

    def test_archive_limit_blocks_only_new_objects(self):
        free = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.FREE)
        free.archive_limit = 1
        free.save(update_fields=['archive_limit'])
        self._card('First')

        with self.assertRaises(subscriptions.SubscriptionLimitError):
            subscriptions.assert_can_create_archive_file(self.user)

    def test_archive_remaining_reports_available_space(self):
        free = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.FREE)
        free.archive_limit = 2
        free.save(update_fields=['archive_limit'])
        self._card('First')

        snapshot = subscriptions.archive_limit_snapshot(self.user)

        self.assertEqual(snapshot.archive_limit, 2)
        self.assertEqual(snapshot.archive_used, 1)
        self.assertEqual(snapshot.archive_remaining, 1)

    def test_limited_tariff_blocks_extra_archive_object_with_clear_message(self):
        free = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.FREE)
        free.archive_limit = 1
        free.save(update_fields=['archive_limit'])
        self._card('First')

        with self.assertRaises(subscriptions.SubscriptionLimitError) as ctx:
            subscriptions.assert_can_create_archive_file(self.user)

        self.assertIn(subscriptions.ARCHIVE_LIMIT_ERROR, ctx.exception.message_dict['archive'])

    def test_active_auction_limit_blocks_new_live_auction(self):
        free = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.FREE)
        free.active_auction_limit = 1
        free.save(update_fields=['active_auction_limit'])
        self._auction_listing('First lot')

        with self.assertRaises(ValidationError):
            self._auction_listing('Second lot')

    def test_existing_archive_data_survives_after_paid_plan_expires(self):
        free = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.FREE)
        free.archive_limit = 1
        free.save(update_fields=['archive_limit'])
        plus = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PLUS)
        plus.archive_limit = 3
        plus.save(update_fields=['archive_limit'])
        starts_at = timezone.now() - timedelta(days=31)
        subscriptions.activate_subscription(
            self.user,
            plus,
            billing_period=UserSubscription.BillingPeriod.MONTH,
            starts_at=starts_at,
        )
        self._card('First')
        self._card('Second')

        subscriptions.expire_due_subscriptions(now=timezone.now())

        self.assertEqual(ArchiveFile.objects.filter(owner=self.user).count(), 2)
        self.assertEqual(subscriptions.get_active_subscription(self.user, refresh=False).plan.code, SubscriptionPlan.Code.FREE)
        with self.assertRaises(subscriptions.SubscriptionLimitError):
            subscriptions.assert_can_create_archive_file(self.user)

    def test_expired_subscription_current_tariff_falls_back_to_free(self):
        free = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.FREE)
        free.archive_limit = 1
        free.save(update_fields=['archive_limit'])
        plus = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PLUS)
        starts_at = timezone.now() - timedelta(days=31)
        subscriptions.activate_subscription(
            self.user,
            plus,
            billing_period=UserSubscription.BillingPeriod.MONTH,
            starts_at=starts_at,
        )

        tariff = subscriptions.current_tariff(self.user)
        snapshot = subscriptions.archive_limit_snapshot(self.user)

        self.assertEqual(tariff.code, SubscriptionPlan.Code.FREE)
        self.assertEqual(snapshot.archive_limit, 1)

    def test_archive_create_api_checks_limit_on_server(self):
        free = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.FREE)
        free.archive_limit = 1
        free.save(update_fields=['archive_limit'])
        self._card('First')
        self.client.force_login(self.user)

        response = self.client.post('/api/archive/files/', data={
            'rubric': str(self.rubric.pk),
            'title': 'Second',
            'status': ArchiveFile.Status.KEEP,
            'data': json.dumps({'title': 'Second'}),
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn(subscriptions.ARCHIVE_LIMIT_ERROR, response.json()['errors']['archive'])
        self.assertEqual(ArchiveFile.objects.filter(owner=self.user).count(), 1)

    def test_archive_state_api_checks_limit_on_server(self):
        free = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.FREE)
        free.archive_limit = 1
        free.save(update_fields=['archive_limit'])
        self.client.force_login(self.user)

        response = self.client.put(
            '/api/archive/state/',
            data=json.dumps({'state': self._archive_state(2)}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(subscriptions.ARCHIVE_LIMIT_ERROR, response.json()['errors']['archive'])

    def test_market_materialize_checks_limit_on_server(self):
        free = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.FREE)
        free.archive_limit = 1
        free.save(update_fields=['archive_limit'])
        self._card('First')

        with self.assertRaises(subscriptions.SubscriptionLimitError):
            market_auction.materialize_archive_file(
                self.user,
                {'card_id': 'json-card-2', 'title': 'Second', 'description': 'From JSON state'},
            )

        self.assertEqual(ArchiveFile.objects.filter(owner=self.user).count(), 1)
