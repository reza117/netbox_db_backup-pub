# netbox-db-backup

NetBox plugin that creates, lists, downloads, and deletes PostgreSQL backups from one page.

NetBox 4.0 or newer. PostgreSQL only. Actions are limited to superusers.

## What you get

Open **Database Backups** at `/plugins/db-backup/`.

- **Create Backup** queues `pg_dump` on the default RQ worker. The row appears immediately as **Running**, and the page refreshes every 5 seconds until the job finishes. While it runs, the file size is shown against the database size, such as `200.0 MB / 964.5 MB`. The finished row shows the real file size.
- A second backup cannot start while one is running.
- `pg_dump` writes a compressed custom-format `.dump` file directly. The worker then runs `pg_restore --list`. A readable file is marked **Verified**. A file that cannot be read is marked **Failed** and removed. The worker job timeout is 6 hours.
- The table lists each file with its date, size, the NetBox version stored at backup time, the running version, a compatibility badge, and the job status.
- **Compatible** means those two versions match. **Version Mismatch** means they do not.
- **Failed** keeps the row and shows the error. The partial file is removed after the row is marked failed.
- **Download** returns a completed file. The row stores a SHA-256 checksum. Check a download with `sha256sum` and compare it with the value on the page. **Delete** removes the file and its record after confirmation.

Free space, database size, reserve, space needed, and status are shown in separate columns. The status is green when a backup can run, and yellow when it would leave less than the reserve free.

## Requirements

- Unix. Linux and other Unix systems are supported. Windows is not supported.
- NetBox 4.0 or newer
- PostgreSQL
- `pg_dump` on the `PATH` of the host or container that runs the RQ worker
- The RQ worker must be able to reach the NetBox database
- `backup_dir` must be writable. In a container, mount that directory as a volume so backups survive a restart

The page checks for `pg_dump` before a backup starts. If it is missing, **Create Backup** stays disabled and the page shows a warning. The worker checks again before `pg_dump` runs.

## Install

From the NetBox virtualenv:

```bash
source /opt/netbox/venv/bin/activate
pip install /path/to/netbox_db_backup
```

Add the plugin in `/opt/netbox/netbox/netbox/configuration.py`:

```python
PLUGINS = [
    'netbox_db_backup',
]

PLUGINS_CONFIG = {
    'netbox_db_backup': {
        'backup_dir': '/opt/netbox/netbox/media/db_backups',
        'min_free_bytes': 5 * 1024 ** 3,
        'keep_backups': 5,
    },
}
```

Apply the migration and restart NetBox and the worker:

```bash
cd /opt/netbox/netbox
python manage.py migrate netbox_db_backup
sudo systemctl restart netbox netbox-rq
```

In a container, restart the NetBox web process and the RQ worker for that image instead of `systemctl`. Install `pg_dump` in the worker image.

Sign in as a superuser and open **Database Backups**.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `backup_dir` | `/opt/netbox/netbox/media/db_backups` | Directory where `.dump` files are stored |
| `min_free_bytes` | `5 * 1024 ** 3` (5 GB) | Space that must remain free after a backup |
| `keep_backups` | `5` | How many verified backups to keep. Older ones are deleted |

`min_free_bytes` can be raised. A lower value is ignored and 5 GB is used. `keep_backups` can be raised. A value below 1 is treated as 1, so the newest backup is kept. Failed rows are left in place.

The backup row stores who started it. A delete removes the file and keeps the row, with the username in **Deleted by**. Automatic cleanup stores `retention` there.

## Disk safety

A backup starts only when:

`free space − current database size ≥ reserve`

The database size comes from `pg_database_size`. The same check runs again in the worker before `pg_dump`. If it fails, the row is marked **Failed** and no backup file is kept.

When space is too low, or a backup is already running, **Create Backup** stays disabled and the page shows a warning.

## Backup files

Files are named `netbox_YYYYMMDD_HHMMSS.dump`. Restore a completed file with `pg_restore`. Each record stores the file name, size, creation time, job status, and the NetBox version that was running when the backup was created.

After an upgrade, run `python manage.py migrate netbox_db_backup` and restart `netbox` and `netbox-rq`.

## License

MIT. Copyright (c) 2026 Najafzadeh Reza. See [LICENSE](LICENSE).
