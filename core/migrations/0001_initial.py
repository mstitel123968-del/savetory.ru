import uuid
from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.CreateModel(name='DesktopPurchase', fields=[
        ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
        ('email', models.EmailField(max_length=254)),
        ('payment_id', models.CharField(blank=True, max_length=64, null=True, unique=True)),
        ('checkout_url', models.URLField(blank=True, max_length=2048)),
        ('status', models.CharField(default='pending', max_length=20)),
        ('created_at', models.DateTimeField(auto_now_add=True)),
    ])]
