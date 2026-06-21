"""Auction lot data model: publication status, item/handover details,
reserve-price rename, auto-extend settings and the ListingImage model.

The reserve price is renamed (auction_min_price -> auction_reserve_price) with a
data-preserving RenameField. Existing listings get status='active'.
"""
from django.db import migrations, models
import django.db.models.deletion


def set_existing_status_active(apps, schema_editor):
    Listing = apps.get_model("market", "Listing")
    Listing.objects.all().update(status="active")


def noop(apps, schema_editor):
    # Reverse: status column is dropped by the reverse AddField, nothing to do.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("market", "0002_listing_category"),
    ]

    operations = [
        # 1. Safe, data-preserving rename of the reserve price.
        migrations.RenameField(
            model_name="listing",
            old_name="auction_min_price",
            new_name="auction_reserve_price",
        ),
        # 2. Publication status (existing rows default to active).
        migrations.AddField(
            model_name="listing",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Черновик"),
                    ("scheduled", "Ожидает начала"),
                    ("active", "Аукцион идёт"),
                    ("completed", "Завершён"),
                    ("cancelled", "Отменён"),
                ],
                db_index=True,
                default="active",
                max_length=16,
            ),
        ),
        # 3. Item presentation / handover details.
        migrations.AddField(
            model_name="listing",
            name="item_condition",
            field=models.CharField(
                blank=True,
                choices=[
                    ("new", "Новый"),
                    ("excellent", "Отличное"),
                    ("good", "Хорошее"),
                    ("satisfactory", "Удовлетворительное"),
                    ("restoration", "Требует восстановления"),
                ],
                default="",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="listing",
            name="location",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="listing",
            name="delivery_methods",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="listing",
            name="delivery_cost",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="listing",
            name="delivery_note",
            field=models.TextField(blank=True, default=""),
        ),
        # 4. Auction auto-extend settings.
        migrations.AddField(
            model_name="listing",
            name="auction_auto_extend",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="listing",
            name="auction_auto_extend_minutes",
            field=models.PositiveIntegerField(default=2),
        ),
        # 5. Independent lot images.
        migrations.CreateModel(
            name="ListingImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(blank=True, null=True, upload_to="listing_images/")),
                ("display_order", models.PositiveIntegerField(default=0)),
                ("is_cover", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="images", to="market.listing")),
                ("source_image", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="core.archivefileimage")),
            ],
            options={
                "ordering": ["display_order", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="listingimage",
            constraint=models.UniqueConstraint(
                condition=models.Q(("source_image__isnull", False)),
                fields=("listing", "source_image"),
                name="uniq_listing_source_image",
            ),
        ),
        migrations.AddConstraint(
            model_name="listingimage",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_cover", True)),
                fields=("listing",),
                name="uniq_listing_cover",
            ),
        ),
        migrations.AddConstraint(
            model_name="listingimage",
            constraint=models.CheckConstraint(
                check=models.Q(("display_order__gte", 0)),
                name="listing_image_order_nonneg",
            ),
        ),
        # 6. Existing listings explicitly set to active.
        migrations.RunPython(set_existing_status_active, noop),
    ]
