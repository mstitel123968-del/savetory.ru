from django.db import migrations, models


def backfill_read_at(apps, schema_editor):
    DirectMessage = apps.get_model('core', 'DirectMessage')
    # Existing messages that are already read get their sent time as read timestamp
    # so the receipt UI has a value to display.
    DirectMessage.objects.filter(is_read=True, read_at__isnull=True).update(read_at=models.F('sent_at'))


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_profile_extended_fields_rubric_updated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='directmessage',
            name='read_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_read_at, noop_reverse),
    ]
