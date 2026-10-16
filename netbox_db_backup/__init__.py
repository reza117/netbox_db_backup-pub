from netbox.plugins import PluginConfig

MIN_FREE_BYTES = 5 * 1024 ** 3


class NetBoxDBBackupConfig(PluginConfig):
    name = "netbox_db_backup"
    verbose_name = "Database Backups"
    description = "Create, list, download, and delete PostgreSQL backups."
    version = "0.1.0"
    author = "netbox_db_backup"
    base_url = "db-backup"
    min_version = "4.0.0"
    default_settings = {
        "backup_dir": "/opt/netbox/netbox/media/db_backups",
        "min_free_bytes": MIN_FREE_BYTES,
    }


config = NetBoxDBBackupConfig
