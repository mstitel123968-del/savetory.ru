"""Initial migration reproducing the Java entity schema in Django."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('display_name', models.CharField(blank=True, max_length=150)),
                ('avatar', models.ImageField(blank=True, null=True, upload_to='avatars/')),
                ('avatar_meta', models.JSONField(blank=True, default=dict)),
                ('privacy_level', models.CharField(default='public', max_length=50)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Rubric',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('slug', models.SlugField(max_length=255)),
                ('is_text_mode', models.BooleanField(default=False)),
                ('field_schema', models.JSONField(default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rubrics', to='core.profile')),
            ],
            options={
                'ordering': ['created_at'],
                'unique_together': {('profile', 'slug')},
            },
        ),
        migrations.CreateModel(
            name='ArchiveFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('data', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('rubric', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='files', to='core.rubric')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ArchiveFileImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='archive/')),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('archive_file', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='core.archivefile')),
            ],
            options={
                'ordering': ['display_order', 'id'],
            },
        ),
    ]
