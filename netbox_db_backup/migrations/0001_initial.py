from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="BackupFile",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("filename", models.CharField(max_length=255)),
                ("file_size", models.BigIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("netbox_version", models.CharField(max_length=64)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
