from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_friendship'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='last_seen_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
