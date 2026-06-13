from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_directmessage'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DirectMessageReaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reaction', models.CharField(choices=[('👍', 'Thumbs up'), ('❤️', 'Heart'), ('😂', 'Laugh'), ('😮', 'Wow'), ('😢', 'Sad')], max_length=8)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reactions', to='core.directmessage')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='direct_message_reactions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['message_id', 'reaction', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='directmessagereaction',
            index=models.Index(fields=['message', 'reaction'], name='dm_reaction_message_idx'),
        ),
        migrations.AddIndex(
            model_name='directmessagereaction',
            index=models.Index(fields=['user', 'updated_at'], name='dm_reaction_user_idx'),
        ),
        migrations.AddConstraint(
            model_name='directmessagereaction',
            constraint=models.UniqueConstraint(fields=('message', 'user'), name='uniq_dm_reaction_per_user'),
        ),
    ]
