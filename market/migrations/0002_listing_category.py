from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="category",
            field=models.CharField(
                choices=[
                    ("collecting", "Коллекционирование"),
                    ("auto", "Авто"),
                    ("realty", "Недвижимость"),
                    ("jobs", "Работа"),
                    ("electronics", "Электроника"),
                    ("home", "Для дома и дачи"),
                    ("fashion", "Одежда, обувь, аксессуары"),
                    ("hobby", "Хобби и отдых"),
                    ("services", "Услуги"),
                ],
                db_index=True,
                default="collecting",
                max_length=32,
            ),
            preserve_default=False,
        ),
    ]
