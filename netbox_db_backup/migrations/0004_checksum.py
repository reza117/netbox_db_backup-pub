from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_db_backup", "0003_expected_size"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupfile",
            name="checksum",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
