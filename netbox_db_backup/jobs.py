import hashlib
import os
import shutil
import subprocess
import threading

from django.conf import settings
from django.db import close_old_connections, connection
from django_rq import job
from netbox.plugins.utils import get_plugin_config

from . import DEFAULT_KEEP_BACKUPS, MIN_FREE_BYTES
from .models import BackupFile, format_bytes

JOB_TIMEOUT_SECONDS = 6 * 60 * 60
PG_DUMP_MISSING = (
    "Backup was not started. pg_dump was not found. "
    "Install the PostgreSQL client tools on the host that runs the RQ worker."
)


def pg_dump_available():
    return shutil.which("pg_dump") is not None


def backup_directory():
    path = get_plugin_config("netbox_db_backup", "backup_dir")
    if not path:
        raise RuntimeError("backup_dir is not configured.")
    return os.path.realpath(path)


def backup_path(filename):
    if not filename or os.path.basename(filename) != filename:
        raise ValueError("Invalid backup filename.")
    root = backup_directory()
    path = os.path.realpath(os.path.join(root, filename))
    if os.path.commonpath([root, path]) != root:
        raise ValueError("Invalid backup path.")
    return path


class StorageStatus:
    def __init__(
        self,
        path,
        total,
        used,
        free,
        required,
        enough,
        warning,
        status_label,
        reserve=None,
        reserve_note="",
    ):
        self.path = path
        self.total = total
        self.used = used
        self.free = free
        self.required = required
        self.enough = enough
        self.warning = warning
        self.status_label = status_label
        self.reserve = reserve
        self.reserve_note = reserve_note

    def _display(self, size):
        if size is None:
            return "Unavailable"
        return format_bytes(size)

    @property
    def free_display(self):
        return self._display(self.free)

    @property
    def total_display(self):
        return self._display(self.total)

    @property
    def used_display(self):
        return self._display(self.used)

    @property
    def required_display(self):
        return self._display(self.required)

    @property
    def reserve_display(self):
        return self._display(self.reserve)

    @property
    def needed_display(self):
        if self.required is None or self.reserve is None:
            return "Unavailable"
        return format_bytes(self.required + self.reserve)


def _existing_storage_path(path):
    current = path
    while not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError(f"Storage path does not exist: {path}")
        current = parent
    return current


def safety_reserve_bytes():
    configured = get_plugin_config("netbox_db_backup", "min_free_bytes")
    try:
        configured = int(configured)
    except (TypeError, ValueError):
        return MIN_FREE_BYTES, "Configured reserve is invalid, so the 5 GB floor is used."
    if configured < MIN_FREE_BYTES:
        return MIN_FREE_BYTES, "Configured reserve is below the 5 GB floor, so 5 GB is used."
    return configured, ""


def database_size_bytes():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        row = cursor.fetchone()
    if not row or row[0] is None:
        raise RuntimeError("Could not read the database size.")
    return int(row[0])


def storage_status():
    path = ""
    total = used = free = required = None
    reserve, reserve_note = safety_reserve_bytes()
    try:
        path = backup_directory()
        usage = shutil.disk_usage(_existing_storage_path(path))
        total, used, free = usage.total, usage.used, usage.free
    except Exception as error:
        return StorageStatus(
            path=path,
            total=total,
            used=used,
            free=free,
            required=required,
            enough=False,
            warning=f"Backup was not started. Host storage could not be checked: {error}",
            status_label="Storage check failed",
            reserve=reserve,
            reserve_note=reserve_note,
        )

    database = settings.DATABASES["default"]
    if "postgresql" not in database.get("ENGINE", ""):
        return StorageStatus(
            path=path,
            total=total,
            used=used,
            free=free,
            required=required,
            enough=False,
            warning="Backup was not started. Database backups require PostgreSQL.",
            status_label="Storage check failed",
            reserve=reserve,
            reserve_note=reserve_note,
        )

    try:
        required = database_size_bytes()
    except Exception as error:
        return StorageStatus(
            path=path,
            total=total,
            used=used,
            free=free,
            required=required,
            enough=False,
            warning=f"Backup was not started. Database size could not be checked: {error}",
            status_label="Storage check failed",
            reserve=reserve,
            reserve_note=reserve_note,
        )

    if free < required + reserve:
        return StorageStatus(
            path=path,
            total=total,
            used=used,
            free=free,
            required=required,
            enough=False,
            warning=(
                f"Backup was not started. Host storage has {format_bytes(free)} free "
                f"of {format_bytes(total)} at {path}. "
                f"The database is {format_bytes(required)} and {format_bytes(reserve)} "
                f"must stay free for NetBox and the host."
            ),
            status_label="Not enough free space",
            reserve=reserve,
            reserve_note=reserve_note,
        )

    return StorageStatus(
        path=path,
        total=total,
        used=used,
        free=free,
        required=required,
        enough=True,
        warning="",
        status_label="Enough free space",
        reserve=reserve,
        reserve_note=reserve_note,
    )


def _pg_dump_command(database, destination):
    command = ["pg_dump", "--no-password", "-Fc", "-f", destination, "-d", database["NAME"]]
    if database.get("USER"):
        command.extend(["-U", database["USER"]])
    if database.get("HOST"):
        command.extend(["-h", database["HOST"]])
    if database.get("PORT"):
        command.extend(["-p", str(database["PORT"])])
    return command


def verify_dump(path):
    if shutil.which("pg_restore") is None:
        raise RuntimeError("pg_restore was not found, so the dump was not verified.")
    result = subprocess.run(
        ["pg_restore", "--list", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(detail or "pg_restore could not read the dump.")


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _watch_file_size(backup_id, path, stop):
    close_old_connections()
    try:
        while not stop.wait(2):
            if os.path.isfile(path):
                BackupFile.objects.filter(
                    pk=backup_id,
                    status=BackupFile.STATUS_RUNNING,
                ).update(file_size=os.path.getsize(path))
    finally:
        close_old_connections()


def keep_backup_count():
    configured = get_plugin_config("netbox_db_backup", "keep_backups")
    try:
        configured = int(configured)
    except (TypeError, ValueError):
        return DEFAULT_KEEP_BACKUPS
    if configured < 1:
        return 1
    return configured


def prune_old_backups():
    keep = keep_backup_count()
    kept = (BackupFile.STATUS_COMPLETED, BackupFile.STATUS_VERIFIED)
    extras = BackupFile.objects.filter(status__in=kept).order_by("-created_at")[keep:]
    for old in extras:
        try:
            path = backup_path(old.filename)
        except ValueError:
            path = None
        if path and os.path.isfile(path):
            os.remove(path)
        old.status = BackupFile.STATUS_DELETED
        old.deleted_by = "retention"
        old.save(update_fields=["status", "deleted_by"])


def _mark_failed(backup, message, destination=None):
    backup.status = BackupFile.STATUS_FAILED
    backup.error = (message or "Backup failed.")[:4000]
    backup.save(update_fields=["status", "error"])
    if destination and os.path.isfile(destination):
        os.remove(destination)


@job("default", timeout=JOB_TIMEOUT_SECONDS)
def create_database_backup(backup_id):
    backup = BackupFile.objects.get(pk=backup_id)
    destination = None
    started_dump = False
    stop_watch = threading.Event()
    watcher = None
    try:
        if not pg_dump_available():
            raise RuntimeError(PG_DUMP_MISSING)

        database = settings.DATABASES["default"]
        if "postgresql" not in database.get("ENGINE", ""):
            raise RuntimeError("Database backups require PostgreSQL.")

        status = storage_status()
        if not status.enough:
            raise RuntimeError(status.warning)

        directory = backup_directory()
        os.makedirs(directory, mode=0o750, exist_ok=True)
        destination = backup_path(backup.filename)
        if os.path.exists(destination):
            raise RuntimeError(f"Backup already exists: {backup.filename}")
        started_dump = True
        watcher = threading.Thread(
            target=_watch_file_size,
            args=(backup.pk, destination, stop_watch),
            daemon=True,
        )
        watcher.start()

        env = os.environ.copy()
        password = database.get("PASSWORD")
        if password:
            env["PGPASSWORD"] = password
        sslmode = (database.get("OPTIONS") or {}).get("sslmode")
        if sslmode:
            env["PGSSLMODE"] = sslmode

        result = subprocess.run(
            _pg_dump_command(database, destination),
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        stop_watch.set()
        watcher.join(timeout=5)
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(detail or f"pg_dump exited {result.returncode}")

        os.chmod(destination, 0o640)
        verify_dump(destination)
        backup.file_size = os.path.getsize(destination)
        backup.checksum = file_sha256(destination)
        backup.status = BackupFile.STATUS_VERIFIED
        backup.error = ""
        backup.save(update_fields=["file_size", "checksum", "status", "error"])
    except Exception as error:
        stop_watch.set()
        if watcher is not None:
            watcher.join(timeout=5)
        _mark_failed(backup, str(error), destination if started_dump else None)
        raise
    else:
        prune_old_backups()
