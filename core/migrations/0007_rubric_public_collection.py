from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_profile_terms_columns_backfill'),
    ]

    operations = [
        migrations.AddField(
            model_name='rubric',
            name='is_public',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='rubric',
            name='public_slug',
            field=models.SlugField(allow_unicode=True, blank=True, db_index=True, default='', max_length=255),
        ),
    ]
