from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_db_backup", "0004_checksum"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupfile",
            name="created_by",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="backupfile",
            name="deleted_by",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
    ]
