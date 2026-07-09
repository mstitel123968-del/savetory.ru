"""Seed the NewsArticle table from the previously hardcoded articles."""
from django.db import migrations


def seed_news(apps, schema_editor):
    NewsArticle = apps.get_model('core', 'NewsArticle')
    if NewsArticle.objects.exists():
        return
    from core.news_seed import INITIAL_NEWS
    for index, item in enumerate(INITIAL_NEWS):
        NewsArticle.objects.create(
            slug=item['slug'],
            title=item['title'],
            preview=item['preview'],
            body=item['body'],
            is_published=True,
            sort_order=index,
        )


def unseed_news(apps, schema_editor):
    NewsArticle = apps.get_model('core', 'NewsArticle')
    slugs = ['kak-sozdat-rubriku', 'sklad-zapustilos']
    NewsArticle.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_newsarticle_profile_block_reason_profile_blocked_at_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_news, unseed_news),
    ]
