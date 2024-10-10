from django.contrib import admin
from django.contrib import messages
from django.utils.timezone import localtime
from django_object_actions import DjangoObjectActions, action
from .models import Backup, BackupLog


@admin.register(Backup)
class BackupAdmin(DjangoObjectActions, admin.ModelAdmin):
    list_display = 'datetime', 'device', 'filepath'
    fields = 'datetime', 'device', 'filepath'
    readonly_fields = 'datetime', 'device', 'filepath'
    list_filter = 'datetime', 'mac',
    actions = 'restore',
    changelist_actions = ('backup',)

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, *args, **kwargs):
        from .tasks import check_backups
        check_backups()
        return super().changelist_view(*args, **kwargs)


    def restore(self, request, queryset):
        if queryset.count() > 1:
            messages.add_message(
                request, messages.ERROR,
                "Please select one snapshot."
            )
            return
        from simo.backups.tasks import restore_backup
        backup = queryset.first()
        restore_backup.delay(backup.id)
        messages.add_message(
            request, messages.WARNING,
            f"Restore command initiated. "
            f"If things go well, your hub will reboot in ~15 minutes to the "
            f"state it was on {localtime(backup.datetime)}. "
        )

    @action(
        label="Backup now!",  # optional
        description="Start backup now!"  # optional
    )
    def backup(modeladmin, request, queryset=None):
        from simo.backups.tasks import perform_backup
        perform_backup.delay()
        messages.add_message(
            request, messages.INFO,
            f"Backup command initiated. "
            f"If things go well, you will see "
            f"a new backup in here in less than 10 mins. "
            f"Check backup logs for errors if not."
        )


@admin.register(BackupLog)
class BackupLogAdmin(admin.ModelAdmin):
    fields = 'datetime', 'level', 'msg'
    list_display = fields
    readonly_fields = fields
    list_fields = fields
    list_filter = 'datetime', 'level'
    search_fields = 'msg',

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


