from netbox.plugins import PluginMenuItem

menu_items = (
    PluginMenuItem(
        link="plugins:netbox_db_backup:backup_list",
        link_text="Database Backups",
        permissions=["is_superuser"],
    ),
)
