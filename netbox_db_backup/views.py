import os

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .jobs import backup_path, create_database_backup, storage_status
from .models import BackupFile, current_netbox_version


class SuperuserRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not request.user.is_superuser:
            return HttpResponseForbidden("Superuser access is required.")
        return super().dispatch(request, *args, **kwargs)


class BackupListView(SuperuserRequiredMixin, View):
    def get(self, request):
        running_version = current_netbox_version()
        backups = [
            {
                "record": backup,
                "compatible": backup.compatible_with(running_version),
            }
            for backup in BackupFile.objects.all()
        ]
        return render(
            request,
            "netbox_db_backup/backup_list.html",
            {
                "backups": backups,
                "current_version": running_version,
                "storage": storage_status(),
            },
        )


class BackupCreateView(SuperuserRequiredMixin, View):
    def post(self, request):
        status = storage_status()
        if not status.enough:
            messages.warning(request, status.warning)
            return redirect("plugins:netbox_db_backup:backup_list")
        try:
            create_database_backup.delay()
        except Exception:
            messages.error(request, "Could not queue the backup job.")
        else:
            messages.info(
                request,
                "Backup job started. Refresh this page when it finishes.",
            )
        return redirect("plugins:netbox_db_backup:backup_list")


class BackupDownloadView(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        backup = get_object_or_404(BackupFile, pk=pk)
        try:
            path = backup_path(backup.filename)
        except ValueError as error:
            raise Http404("Backup file not found.") from error
        if not os.path.isfile(path):
            raise Http404("Backup file not found.")
        handle = open(path, "rb")
        return FileResponse(handle, as_attachment=True, filename=backup.filename)


class BackupDeleteView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        backup = get_object_or_404(BackupFile, pk=pk)
        try:
            path = backup_path(backup.filename)
        except ValueError:
            path = None
        if path and os.path.isfile(path):
            os.remove(path)
        backup.delete()
        messages.success(request, "Backup deleted.")
        return redirect("plugins:netbox_db_backup:backup_list")
