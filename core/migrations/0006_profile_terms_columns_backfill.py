from django.db import migrations, models


def add_missing_profile_fields(apps, schema_editor):
    Profile = apps.get_model("core", "Profile")
    table_name = Profile._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        existing = {
            col.name for col in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }

    wanted_fields = [
        ("link", models.CharField(max_length=255, blank=True, default="")),
        ("terms_version_accepted", models.CharField(max_length=20, blank=True, default="")),
        ("terms_accepted_at", models.DateTimeField(blank=True, null=True)),
        ("terms_accepted_ip", models.GenericIPAddressField(blank=True, null=True)),
    ]

    for name, field in wanted_fields:
        if name in existing:
            continue
        field.set_attributes_from_name(name)
        schema_editor.add_field(Profile, field)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_archivestate_review"),
    ]

    operations = [
        migrations.RunPython(add_missing_profile_fields, migrations.RunPython.noop),
    ]
