import json
import os
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    ArchiveFile,
    DirectMessage,
    Friendship,
    NewsArticle,
    Profile,
    Review,
    Rubric,
    SubscriptionPayment,
    SubscriptionPlan,
    UserSubscription,
)
from core.services import subscriptions
from core.services.profile_page import build_extended_profile_context
from market.models import Listing


class StudioAdminAccessTests(TestCase):
    def setUp(self):
        self.env = mock.patch.dict(
            os.environ,
            {"SUPERUSER_LOGIN": "SuperUser", "SUPERUSER_PASSWORD": "secret-admin-pass"},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        User = get_user_model()
        self.user = User.objects.create_user("regular", password="pass1234")
        Profile.objects.create(user=self.user, terms_version_accepted="2024-01")

    def admin_login(self):
        return self.client.post(
            reverse("core:studio-login"),
            data=json.dumps({"username": "SuperUser", "password": "secret-admin-pass"}),
            content_type="application/json",
        )

    def test_regular_user_session_does_not_access_studio_api(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("core:studio-news-list"))

        self.assertEqual(response.status_code, 403)

    def test_studio_login_uses_separate_session_without_django_user(self):
        response = self.admin_login()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertFalse(get_user_model().objects.filter(username="SuperUser").exists())
        self.assertFalse(self.client.get(reverse("core:auth-status")).json()["authenticated"])
        self.assertTrue(self.client.get(reverse("core:studio-status")).json()["authenticated"])

    def test_studio_logout_only_clears_admin_session(self):
        self.client.force_login(self.user)
        self.admin_login()

        self.client.post(reverse("core:studio-logout"))

        self.assertFalse(self.client.get(reverse("core:studio-status")).json()["authenticated"])
        self.assertTrue(self.client.get(reverse("core:auth-status")).json()["authenticated"])

    def test_studio_admin_can_manage_news_users_listings_and_reviews(self):
        User = get_user_model()
        target = User.objects.create_user("target", password="pass1234")
        target_profile = Profile.objects.create(user=target, terms_version_accepted="2024-01")
        rubric = Rubric.objects.create(profile=target_profile, name="Things", slug="things")
        item = ArchiveFile.objects.create(rubric=rubric, owner=target, title="Lot item")
        listing = Listing.objects.create(
            item=item,
            seller=target,
            type=Listing.Type.AUCTION,
            category=Listing.Category.COLLECTING,
            title="Auction lot",
            status=Listing.Status.ACTIVE,
            is_active=True,
            auction_start=timezone.now() - timedelta(hours=1),
            auction_end=timezone.now() + timedelta(hours=1),
            auction_start_price=Decimal("100.00"),
            auction_reserve_price=Decimal("150.00"),
            auction_step=Decimal("10.00"),
            current_price=Decimal("100.00"),
        )
        review = Review.objects.create(user=target, rating=5, text="Good")
        self.admin_login()

        news_response = self.client.post(
            reverse("core:studio-news-save"),
            data={"title": "Admin news", "preview": "Preview", "body": "Body", "is_published": "1"},
        )
        self.assertEqual(news_response.status_code, 200)
        self.assertTrue(NewsArticle.objects.filter(title="Admin news", is_published=True).exists())

        block_response = self.client.post(
            reverse("core:studio-user-block", args=[target.pk]),
            data=json.dumps({"reason": "rules"}),
            content_type="application/json",
        )
        self.assertEqual(block_response.status_code, 200)
        target.profile.refresh_from_db()
        self.assertTrue(target.profile.is_blocked)
        self.assertIsNone(target.profile.blocked_by)

        unblock_response = self.client.post(reverse("core:studio-user-unblock", args=[target.pk]))
        self.assertEqual(unblock_response.status_code, 200)
        target.profile.refresh_from_db()
        self.assertFalse(target.profile.is_blocked)

        listing_response = self.client.post(
            reverse("core:studio-listing-action", args=[listing.pk]),
            data=json.dumps({"action": "invalidate", "reason": "bad lot"}),
            content_type="application/json",
        )
        self.assertEqual(listing_response.status_code, 200)
        listing.refresh_from_db()
        self.assertTrue(listing.is_invalidated)
        self.assertIsNone(listing.moderated_by)
        self.assertIsNone(listing.cancelled_by)

        reactivate_response = self.client.post(
            reverse("core:studio-listing-action", args=[listing.pk]),
            data=json.dumps({"action": "reactivate"}),
            content_type="application/json",
        )
        self.assertEqual(reactivate_response.status_code, 200)
        listing.refresh_from_db()
        self.assertTrue(listing.is_active)
        self.assertFalse(listing.is_invalidated)

        unpublish_response = self.client.post(
            reverse("core:studio-listing-action", args=[listing.pk]),
            data=json.dumps({"action": "unpublish", "reason": "unpublished by admin"}),
            content_type="application/json",
        )
        self.assertEqual(unpublish_response.status_code, 200)
        listing.refresh_from_db()
        self.assertTrue(listing.is_unpublished)
        self.assertFalse(listing.is_active)

        self.client.post(
            reverse("core:studio-listing-action", args=[listing.pk]),
            data=json.dumps({"action": "reactivate"}),
            content_type="application/json",
        )
        listing.refresh_from_db()
        self.assertFalse(listing.is_unpublished)

        close_response = self.client.post(
            reverse("core:studio-listing-action", args=[listing.pk]),
            data=json.dumps({"action": "close", "reason": "closed by admin"}),
            content_type="application/json",
        )
        self.assertEqual(close_response.status_code, 200)
        listing.refresh_from_db()
        self.assertEqual(listing.status, Listing.Status.COMPLETED)

        review_response = self.client.post(
            reverse("core:studio-review-action", args=[review.pk]),
            data=json.dumps({"action": "hide", "reason": "moderation"}),
            content_type="application/json",
        )
        self.assertEqual(review_response.status_code, 200)
        review.refresh_from_db()
        self.assertTrue(review.is_hidden)
        self.assertIsNone(review.hidden_by)

        restore_response = self.client.post(
            reverse("core:studio-review-action", args=[review.pk]),
            data=json.dumps({"action": "restore"}),
            content_type="application/json",
        )
        self.assertEqual(restore_response.status_code, 200)
        review.refresh_from_db()
        self.assertFalse(review.is_hidden)

        delete_response = self.client.post(
            reverse("core:studio-review-action", args=[review.pk]),
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())

    def test_studio_diagnostics_requires_admin_session(self):
        response = self.client.get(reverse("core:studio-diagnostics"))

        self.assertEqual(response.status_code, 403)

    @override_settings(
        YOOKASSA_SHOP_ID="shop-1",
        YOOKASSA_SECRET_KEY="secret-token-that-must-not-leak",
        YOOKASSA_RETURN_URL="https://savetory.ru/subscriptions/payment/result/",
    )
    def test_studio_diagnostics_hides_yookassa_secret(self):
        subscriptions.seed_default_plans()
        self.admin_login()

        response = self.client.get(reverse("core:studio-diagnostics"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["yookassa"]["configured"])
        self.assertTrue(payload["yookassa"]["secret_key_configured"])
        self.assertNotIn("secret-token-that-must-not-leak", json.dumps(payload))

    @override_settings(
        YOOKASSA_SHOP_ID="shop-1",
        YOOKASSA_SECRET_KEY="secret-token-that-must-not-leak",
        YOOKASSA_RETURN_URL="https://savetory.ru/subscriptions/payment/result/",
    )
    def test_studio_payment_sync_activates_paid_yookassa_payment(self):
        subscriptions.seed_default_plans()
        plus = SubscriptionPlan.objects.get(code=SubscriptionPlan.Code.PLUS)
        payment = SubscriptionPayment.objects.create(
            user=self.user,
            tariff=plus,
            period=SubscriptionPayment.Period.MONTH,
            amount=Decimal("99.00"),
            currency="RUB",
            status=SubscriptionPayment.Status.PENDING,
            yookassa_payment_id="yk-diagnostic-sync",
            idempotence_key="idem-diagnostic-sync",
            metadata={
                "internal_payment_id": "",
                "user_id": str(self.user.pk),
                "plan": SubscriptionPlan.Code.PLUS,
                "period": SubscriptionPayment.Period.MONTH,
            },
        )
        payment.metadata["internal_payment_id"] = str(payment.internal_uuid)
        payment.save(update_fields=["metadata"])
        remote = {
            "id": payment.yookassa_payment_id,
            "status": SubscriptionPayment.Status.SUCCEEDED,
            "paid": True,
            "amount": {"value": "99.00", "currency": "RUB"},
            "metadata": payment.metadata,
        }
        self.admin_login()

        with mock.patch("core.services.subscriptions._fetch_yookassa_payment", return_value=remote):
            response = self.client.post(
                reverse("core:studio-payment-sync"),
                data=json.dumps({"payment_id": payment.yookassa_payment_id}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["activated"])
        payment.refresh_from_db()
        self.assertTrue(payment.subscription_activated)
        active = UserSubscription.objects.get(user=self.user, status=UserSubscription.Status.ACTIVE)
        self.assertEqual(active.tariff.code, SubscriptionPlan.Code.PLUS)


class ReservedSuperUserVisibilityTests(TestCase):
    def setUp(self):
        self.env = mock.patch.dict(
            os.environ,
            {"SUPERUSER_LOGIN": "SuperUser", "SUPERUSER_PASSWORD": "secret-admin-pass"},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        User = get_user_model()
        self.viewer = User.objects.create_user("viewer", password="pass1234")
        self.legacy = User.objects.create_user("SuperUser", password="pass1234")
        Profile.objects.create(user=self.viewer, terms_version_accepted="2024-01")
        Profile.objects.create(user=self.legacy, terms_version_accepted="2024-01")
        self.client.force_login(self.viewer)

    def test_reserved_admin_user_is_hidden_from_public_user_flows(self):
        self.client.logout()
        regular_login = self.client.post(
            reverse("core:login"),
            data={"username": "SuperUser", "password": "pass1234"},
        )
        self.assertEqual(regular_login.status_code, 403)
        self.client.force_login(self.viewer)

        search = self.client.get(reverse("core:community-search-api"), {"q": "SuperUser"})
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()["users"], [])

        profile_page = build_extended_profile_context(self.viewer, "SuperUser")
        self.assertFalse(profile_page["found"])

        friendship = self.client.post(
            reverse("core:community-friendship-api"),
            data=json.dumps({"action": "send", "target_id": self.legacy.pk}),
            content_type="application/json",
        )
        self.assertEqual(friendship.status_code, 404)

        message = self.client.post(
            reverse("core:message-send-api"),
            data=json.dumps({"recipient_id": self.legacy.pk, "text": "hello"}),
            content_type="application/json",
        )
        self.assertEqual(message.status_code, 404)

    def test_cleanup_command_disables_legacy_reserved_user_and_social_edges(self):
        user_low, user_high = Friendship.normalize_pair(self.viewer, self.legacy)
        Friendship.objects.create(
            user_low=user_low,
            user_high=user_high,
            requester=self.viewer,
            status=Friendship.Status.ACCEPTED,
        )
        DirectMessage.objects.create(sender=self.viewer, recipient=self.legacy, text="old")

        call_command("ensure_superuser", verbosity=0)

        self.legacy.refresh_from_db()
        self.legacy.profile.refresh_from_db()
        self.assertFalse(self.legacy.is_active)
        self.assertFalse(self.legacy.is_staff)
        self.assertFalse(self.legacy.is_superuser)
        self.assertTrue(self.legacy.profile.is_hidden)
        self.assertTrue(self.legacy.profile.is_blocked)
        self.assertFalse(Friendship.objects.exists())
        self.assertFalse(DirectMessage.objects.exists())
