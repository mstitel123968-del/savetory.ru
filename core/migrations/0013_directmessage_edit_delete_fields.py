from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_directmessagereaction'),
    ]

    operations = [
        migrations.AddField(
            model_name='directmessage',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='directmessage',
            name='edited_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='directmessage',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
    ]
