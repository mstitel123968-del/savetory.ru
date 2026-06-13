from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_profile_last_seen_at'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DirectMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.TextField()),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('is_read', models.BooleanField(default=False)),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='received_direct_messages', to=settings.AUTH_USER_MODEL)),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sent_direct_messages', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['sent_at', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='directmessage',
            index=models.Index(fields=['sender', 'recipient', 'sent_at'], name='dm_sender_recipient_idx'),
        ),
        migrations.AddIndex(
            model_name='directmessage',
            index=models.Index(fields=['recipient', 'sender', 'sent_at'], name='dm_recipient_sender_idx'),
        ),
        migrations.AddIndex(
            model_name='directmessage',
            index=models.Index(fields=['recipient', 'is_read'], name='dm_recipient_read_idx'),
        ),
        migrations.AddConstraint(
            model_name='directmessage',
            constraint=models.CheckConstraint(check=models.Q(('sender_id', models.F('recipient_id')), _negated=True), name='dm_sender_not_recipient'),
        ),
    ]
