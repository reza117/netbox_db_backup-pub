from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_db_backup", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupfile",
            name="status",
            field=models.CharField(default="completed", max_length=16),
        ),
        migrations.AddField(
            model_name="backupfile",
            name="error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="backupfile",
            name="file_size",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddConstraint(
            model_name="backupfile",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="running"),
                fields=("status",),
                name="netbox_db_backup_one_running",
            ),
        ),
    ]
