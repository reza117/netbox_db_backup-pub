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
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_VERIFIED = "verified"
    STATUS_FAILED = "failed"
    STATUS_DELETED = "deleted"

    filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField(default=0)
    expected_size = models.BigIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True, default="")
    created_by = models.CharField(max_length=150, blank=True, default="")
    deleted_by = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    netbox_version = models.CharField(max_length=64)
    status = models.CharField(max_length=16, default=STATUS_COMPLETED)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["status"],
                condition=models.Q(status="running"),
                name="netbox_db_backup_one_running",
            )
        ]

    def __str__(self):
        return self.filename

    @property
    def size_display(self):
        return format_bytes(self.file_size)

    @property
    def progress_display(self):
        if self.status == self.STATUS_RUNNING and self.expected_size:
            return f"{format_bytes(self.file_size)} / {format_bytes(self.expected_size)}"
        if self.status in (self.STATUS_COMPLETED, self.STATUS_VERIFIED, self.STATUS_DELETED):
            return format_bytes(self.file_size)
        return "—"

    def compatible_with(self, running_version):
        return (self.netbox_version or "").strip() == (running_version or "").strip()

    @classmethod
    def in_progress(cls):
        return cls.objects.filter(status=cls.STATUS_RUNNING).exists()
