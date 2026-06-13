# Generated manually because the local environment does not include Django.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0008_archivefile_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='Friendship',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('rejected', 'Rejected')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('requester', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sent_friendship_requests', to=settings.AUTH_USER_MODEL)),
                ('user_high', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='friendships_as_high', to=settings.AUTH_USER_MODEL)),
                ('user_low', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='friendships_as_low', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='friendship',
            constraint=models.UniqueConstraint(fields=('user_low', 'user_high'), name='uniq_friendship_pair'),
        ),
        migrations.AddConstraint(
            model_name='friendship',
            constraint=models.CheckConstraint(check=models.Q(user_low_id__lt=models.F('user_high_id')), name='friendship_ordered_pair'),
        ),
        migrations.AddConstraint(
            model_name='friendship',
            constraint=models.CheckConstraint(
                check=models.Q(requester_id=models.F('user_low_id')) | models.Q(requester_id=models.F('user_high_id')),
                name='friendship_requester_is_participant',
            ),
        ),
        migrations.AddIndex(
            model_name='friendship',
            index=models.Index(fields=['user_low', 'status'], name='friend_low_status_idx'),
        ),
        migrations.AddIndex(
            model_name='friendship',
            index=models.Index(fields=['user_high', 'status'], name='friend_high_status_idx'),
        ),
        migrations.AddIndex(
            model_name='friendship',
            index=models.Index(fields=['requester', 'status'], name='friend_requester_status_idx'),
        ),
    ]
