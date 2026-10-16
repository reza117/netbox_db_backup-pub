import gzip
import os
import shutil
import subprocess
import threading

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_rq import job
from netbox.plugins.utils import get_plugin_config

from . import MIN_FREE_BYTES
from .models import BackupFile, current_netbox_version, format_bytes


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


def _pg_dump_command(database):
    command = ["pg_dump", "--no-password", "-d", database["NAME"]]
    if database.get("USER"):
        command.extend(["-U", database["USER"]])
    if database.get("HOST"):
        command.extend(["-h", database["HOST"]])
    if database.get("PORT"):
        command.extend(["-p", str(database["PORT"])])
    return command


@job("default")
def create_database_backup():
    database = settings.DATABASES["default"]
    engine = database.get("ENGINE", "")
    if "postgresql" not in engine:
        raise RuntimeError("Database backups require PostgreSQL.")

    status = storage_status()
    if not status.enough:
        raise RuntimeError(status.warning)

    directory = backup_directory()
    os.makedirs(directory, mode=0o750, exist_ok=True)
    filename = f"netbox_{timezone.now().strftime('%Y%m%d_%H%M%S')}.sql.gz"
    destination = backup_path(filename)
    if os.path.exists(destination):
        raise RuntimeError(f"Backup already exists: {filename}")

    env = os.environ.copy()
    password = database.get("PASSWORD")
    if password:
        env["PGPASSWORD"] = password
    sslmode = (database.get("OPTIONS") or {}).get("sslmode")
    if sslmode:
        env["PGSSLMODE"] = sslmode

    process = subprocess.Popen(
        _pg_dump_command(database),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    stderr_parts = []

    def _capture_stderr():
        stderr_parts.append(process.stderr.read())

    stderr_reader = threading.Thread(target=_capture_stderr)
    stderr_reader.start()
    try:
        with gzip.open(destination, "wb") as handle:
            while True:
                chunk = process.stdout.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        stderr_reader.join()
        return_code = process.wait()
        stderr = b"".join(stderr_parts).decode(errors="replace").strip()
        if return_code != 0:
            raise RuntimeError(stderr or f"pg_dump exited {return_code}")
        os.chmod(destination, 0o640)
        BackupFile.objects.create(
            filename=filename,
            file_size=os.path.getsize(destination),
            netbox_version=current_netbox_version(),
        )
    except Exception:
        if os.path.exists(destination):
            os.remove(destination)
        raise
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        stderr_reader.join()
        for stream in (process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()
