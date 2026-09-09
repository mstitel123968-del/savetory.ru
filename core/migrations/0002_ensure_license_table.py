from django.db import migrations

def ensure_table(apps, schema_editor):
    model = apps.get_model('core', 'DesktopPurchase')
    if model._meta.db_table not in schema_editor.connection.introspection.table_names():
        schema_editor.create_model(model)

class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial')]
    operations = [migrations.RunPython(ensure_table, migrations.RunPython.noop)]
