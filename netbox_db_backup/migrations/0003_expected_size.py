from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_db_backup", "0002_backup_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupfile",
            name="expected_size",
            field=models.BigIntegerField(default=0),
        ),
    ]
