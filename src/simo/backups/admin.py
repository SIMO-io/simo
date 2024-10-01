from django.contrib import admin
from .models import Backup


@admin.register(Backup)
class BackupAdmin(admin.ModelAdmin):
    list_display = 'datetime', 'device', 'filepath'
    fields = 'datetime', 'device', 'filepath'
    readonly_fields = 'datetime', 'device', 'filepath'
    list_filter = 'datetime', 'mac',

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False