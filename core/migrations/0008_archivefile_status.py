from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_rubric_public_collection'),
    ]

    operations = [
        migrations.AddField(
            model_name='archivefile',
            name='status',
            field=models.CharField(
                choices=[
                    ('keep', 'Храню'),
                    ('sell', 'Готов продать'),
                    ('exchange', 'Готов обменять'),
                    ('search', 'Ищу такой же'),
                    ('sold', 'Продано'),
                ],
                default='keep',
                max_length=20,
            ),
        ),
    ]
