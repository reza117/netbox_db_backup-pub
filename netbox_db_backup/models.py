from django.conf import settings
from django.db import models


def current_netbox_version():
    version = getattr(settings, "VERSION", "")
    if isinstance(version, (list, tuple)):
        return ".".join(str(part) for part in version)
    return str(version)


def format_bytes(size):
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size or 0)} B"


class BackupFile(models.Model):
    filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    netbox_version = models.CharField(max_length=64)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.filename

    @property
    def size_display(self):
        return format_bytes(self.file_size)

    def compatible_with(self, running_version):
        return (self.netbox_version or "").strip() == (running_version or "").strip()
