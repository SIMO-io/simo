from threading import Timer
from django.contrib import admin
from django.utils.safestring import mark_safe
from django.template.loader import render_to_string
from django.templatetags.static import static
from simo.core.models import Component
from simo.core.utils.admin import FormAction
from .models import Colonel, Interface, ColonelPin
from .forms import ColonelAdminForm, MoveColonelForm, InterfaceAdminForm


class InterfaceInline(admin.TabularInline):
    model = Interface
    extra = 0
    form = InterfaceAdminForm


class ColonelPinsInline(admin.TabularInline):
    model = ColonelPin
    extra = 0
    fields = 'id_display', 'label', 'occupied_by_display',
    readonly_fields = fields

    def occupied_by_display(self, obj):
        if not obj.occupied_by:
            return
        try:
            admin_url = obj.occupied_by.get_admin_url()
        except:
            admin_url = None
        txt = f'{obj.occupied_by_content_type}: {obj.occupied_by}'
        if admin_url:
            return mark_safe(f'<a href="{admin_url}">{txt}</a>')
        return txt

    occupied_by_display.short_description = "Occupied By"


    def id_display(self, obj):
        return obj.id
    id_display.short_description = "ID"

    def has_add_permission(self, request, obj):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Colonel)
class ColonelAdmin(admin.ModelAdmin):
    form = ColonelAdminForm
    list_display = (
        '__str__', 'instance', 'type', 'connected', 'last_seen', 'firmware_version',
        'newer_firmware_available',
    )
    readonly_fields = (
        'type', 'uid', 'connected', 'last_seen',
        'firmware_version', 'newer_firmware_available',
    )
    fields = (
        'name', 'instance', 'enabled', 'firmware_auto_update'
    ) + readonly_fields + ('pwm_frequency', 'logs_stream', 'log', )

    actions = (
        'check_for_upgrade', 'update_firmware', 'update_config', 'restart',
        FormAction(MoveColonelForm, 'move_colonel_to', "Move to other Colonel"),
        'rebuild_occupied_pins'
    )

    inlines = InterfaceInline, ColonelPinsInline

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_master:
            return qs
        return qs.filter(instance__in=request.user.instances)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # give it one second to finish up with atomic transaction and
        # send update_config command.
        def update_colonel_config(colonel):
            colonel.update_config()
        Timer(1, update_colonel_config, [obj]).start()


    def has_add_permission(self, request):
        return False

    def update_firmware(self, request, queryset):
        count = 0
        for colonel in queryset:
            if colonel.instance not in request.user.instances:
                continue
            if colonel.major_upgrade_available:
                colonel.update_firmware(colonel.major_upgrade_available)
                count += 1
            elif colonel.minor_upgrade_available:
                colonel.update_firmware(colonel.minor_upgrade_available)
                count += 1

        self.message_user(
            request, "%d firmware update commands dispatched." % count
        )

    def move_colonel_to(self, request, queryset, form):
        if form.cleaned_data['colonel'].instance not in request.user.instances:
            return
        moved = 0
        for colonel in queryset:
            if colonel.instance not in request.user.instances:
                continue
            moved += 1
            colonel.move_to(form.cleaned_data['colonel'])
        if moved:
            self.message_user(
                request, "%d colonels were moved." % moved
            )

    def restart(self, request, queryset):
        restarted = 0
        for colonel in queryset:
            if colonel.instance not in request.user.instances:
                continue
            restarted += 1
            colonel.restart()
        if restarted:
            self.message_user(
                request, "%d colonels were restarted." % restarted
            )

    def update_config(self, request, queryset):
        affected = 0
        for colonel in queryset:
            if colonel.instance not in request.user.instances:
                continue
            affected += 1
            colonel.update_config()
        if affected:
            self.message_user(
                request, "%d colonels were updated." % affected
            )

    def check_for_upgrade(self, request, queryset):
        for colonel in queryset:
            colonel.check_for_upgrade()
        self.message_user(
            request, "%d colonels checked." % queryset.count()
        )

    def rebuild_occupied_pins(self, request, queryset):
        affected = 0
        for obj in queryset:
            affected += 1
            obj.rebuild_occupied_pins()

        self.message_user(
            request, f"Occupied pins where rebuilt on {affected} colonels."
        )

    def connected(self, obj):
        if obj.is_connected:
            return mark_safe('<img src="%s" alt="True">' % static('admin/img/icon-yes.svg'))
        return mark_safe('<img src="%s" alt="False">' % static('admin/img/icon-no.svg'))


@admin.register(Interface)
class InterfaceAdmin(admin.ModelAdmin):
    list_filter = 'colonel', 'type'
    actions = 'broadcast_reset'

    def broadcast_reset(self, request, queryset):
        broadcasted = 0
        for interface in queryset.filter(
            colonel__socket_connected=True
        ):
            interface.broadcast_reset()
            broadcasted += 1

        if broadcasted:
            self.message_user(
                request,
                f"Reset command was broadcased to {broadcasted} interfaces."
            )
        else:
            self.message_user(
                request,
                f"No reset command was broadcasted, "
                f"probably because they are out of reach at the moment."
            )

    broadcast_reset.short_description = "Broadcast RESET command"