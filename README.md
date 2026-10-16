# netbox-db-backup

NetBox plugin that creates, lists, downloads, and deletes PostgreSQL backups from one page.

NetBox 4.0 or newer. PostgreSQL only. Actions are limited to superusers.

## What you get

Open **Database Backups** at `/plugins/db-backup/`.

- **Create Backup** queues `pg_dump` on the default RQ worker and writes a `.sql.gz` file.
- The table lists each file with its date, size, the NetBox version stored at backup time, the running version, and a compatibility badge.
- **Compatible** means those two versions match. **Version Mismatch** means they do not.
- **Download** returns the file. **Delete** removes the file and its record after confirmation.

The page also shows free disk space, the database size, and the safety reserve.

## Requirements

- NetBox 4.0 or newer
- PostgreSQL, with `pg_dump` installed on the host that runs the RQ worker
- The RQ worker must be able to reach the NetBox database

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
    },
}
```

Apply the migration and restart NetBox and the worker:

```bash
cd /opt/netbox/netbox
python manage.py migrate netbox_db_backup
sudo systemctl restart netbox netbox-rq
```

Sign in as a superuser and open **Database Backups**.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `backup_dir` | `/opt/netbox/netbox/media/db_backups` | Directory where `.sql.gz` files are stored |
| `min_free_bytes` | `5 * 1024 ** 3` (5 GB) | Space that must remain free after a backup |

`min_free_bytes` can be raised. A lower value is ignored and 5 GB is used.

## Disk safety

A backup starts only when:

`free space − current database size ≥ reserve`

The database size comes from `pg_database_size`. The same check runs again in the worker before `pg_dump`. If it fails, the job does not write a file.

When space is too low, **Create Backup** stays disabled and the page shows a warning.

## Backup files

Files are named `netbox_YYYYMMDD_HHMMSS.sql.gz`. Each record stores the file name, size, creation time, and the NetBox version that was running when the backup was created.
