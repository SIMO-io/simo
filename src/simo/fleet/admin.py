from threading import Timer
from actstream.models import actor_stream
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from simo.core.middleware import get_current_instance
from simo.core.utils.admin import FormAction
from .models import (
    Colonel, Interface, ColonelPin,
    DALI_BROADCAST_ACTION_CHOICES, DALI_BROADCAST_ACTION_LABELS
)
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
        'history', 'wake_stats', 'last_wake', 'is_vo_active'
    )

    actions = (
        'check_for_upgrade', 'update_firmware', 'update_config', 'restart',
        FormAction(MoveColonelForm, 'move_colonel_to', "Move to other Colonel"),
        'rebuild_occupied_pins'
    )

    inlines = InterfaceInline, ColonelPinsInline

    fieldsets = (
        ("", {'fields': (
            'name', 'instance', 'enabled', 'firmware_auto_update',
            'type', 'uid', 'connected', 'last_seen',
            'firmware_version', 'newer_firmware_available',
            'logs_stream', 'log'
        )}),
        ("History", {
            'fields': ('history',),
            'classes': ('collapse',),
        }),
        ("AI Voice Assistant", {
            'fields': ('wake_stats', 'last_wake', 'is_vo_active'),
            'classes': ('collapse',),
        })
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(instance=get_current_instance())

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

    def history(self, obj):
        if not obj:
            return ''
        actions = actor_stream(obj)[:100]
        if not len(actions):
            return ''
        return render_to_string(
            'admin/colonel_history.html', {'actions': actor_stream(obj)[:100]}
        )

@admin.register(Interface)
class InterfaceAdmin(admin.ModelAdmin):
    list_display = (
        '__str__', 'colonel', 'type', 'connected', 'dali_broadcast_controls'
    )
    list_filter = 'colonel', 'type'
    readonly_fields = 'pin_a', 'pin_b', 'dali_broadcast_controls'
    fields = (
        'colonel', 'no', 'type', 'pin_a', 'pin_b',
        'dali_broadcast_controls'
    )
    actions = (
        'dali_power_off', 'dali_power_on', 'dali_recall_min',
        'dali_level_50', 'dali_identify', 'broadcast_reset',
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'colonel', 'colonel__instance'
        ).filter(colonel__instance=get_current_instance())

    def get_urls(self):
        return [
            path(
                '<path:object_id>/dali-broadcast/<str:action>/',
                self.admin_site.admin_view(self.dali_broadcast_view),
                name='fleet_interface_dali_broadcast'
            ),
        ] + super().get_urls()

    def dali_broadcast_view(self, request, object_id, action):
        obj = self.get_object(request, object_id)
        if obj is None:
            self.message_user(
                request, "Interface was not found.", level=messages.ERROR
            )
            return HttpResponseRedirect(
                reverse('admin:fleet_interface_changelist')
            )
        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        self._dispatch_dali_broadcast(
            request, Interface.objects.filter(pk=obj.pk), action
        )
        return HttpResponseRedirect(
            reverse('admin:fleet_interface_change', args=[obj.pk])
        )

    def _dispatch_dali_broadcast(self, request, queryset, action):
        label = DALI_BROADCAST_ACTION_LABELS.get(action, action)
        broadcasted = 0
        skipped = 0
        for interface in queryset.filter(type='dali').select_related(
            'colonel', 'colonel__instance'
        ):
            if interface.colonel.instance not in request.user.instances:
                skipped += 1
                continue
            if not interface.colonel.is_connected:
                skipped += 1
                continue
            try:
                if interface.dali_broadcast(action):
                    broadcasted += 1
                else:
                    skipped += 1
            except ValidationError as e:
                skipped += 1
                self.message_user(request, str(e), level=messages.ERROR)

        if broadcasted:
            self.message_user(
                request,
                f"{label} DALI broadcast dispatched to {broadcasted} interfaces."
            )
        else:
            self.message_user(
                request,
                f"No {label} DALI broadcasts were dispatched.",
                level=messages.WARNING
            )
        if skipped:
            self.message_user(
                request,
                f"{skipped} interfaces were skipped because they were not DALI, "
                f"offline, or outside your instance.",
                level=messages.WARNING
            )

    def dali_power_off(self, request, queryset):
        self._dispatch_dali_broadcast(request, queryset, 'off')

    dali_power_off.short_description = "DALI broadcast: Power OFF"

    def dali_power_on(self, request, queryset):
        self._dispatch_dali_broadcast(request, queryset, 'on')

    dali_power_on.short_description = "DALI broadcast: Power ON / max"

    def dali_recall_min(self, request, queryset):
        self._dispatch_dali_broadcast(request, queryset, 'min')

    dali_recall_min.short_description = "DALI broadcast: Recall MIN"

    def dali_level_50(self, request, queryset):
        self._dispatch_dali_broadcast(request, queryset, 'level_50')

    dali_level_50.short_description = "DALI broadcast: Set 50%"

    def dali_identify(self, request, queryset):
        self._dispatch_dali_broadcast(request, queryset, 'identify')

    dali_identify.short_description = "DALI broadcast: Identify gear"

    def connected(self, obj):
        if obj.colonel.is_connected:
            return mark_safe(
                '<img src="%s" alt="True">'
                % static('admin/img/icon-yes.svg')
            )
        return mark_safe(
            '<img src="%s" alt="False">'
            % static('admin/img/icon-no.svg')
        )

    connected.short_description = "Colonel connected"

    def dali_broadcast_controls(self, obj):
        if not obj or not obj.pk:
            return ''
        if obj.type != 'dali':
            return ''
        if not obj.colonel.is_connected:
            return "Colonel offline"

        links = []
        for action, label in DALI_BROADCAST_ACTION_CHOICES:
            url = reverse(
                'admin:fleet_interface_dali_broadcast',
                args=[obj.pk, action]
            )
            links.append(format_html(
                '<a class="button" style="margin-right: 4px;" href="{}">{}</a>',
                url, label
            ))
        return format_html_join('', '{}', ((link,) for link in links))

    dali_broadcast_controls.short_description = "DALI diagnostics"

    def broadcast_reset(self, request, queryset):
        broadcasted = 0
        for interface in queryset.filter(type='dali').select_related(
            'colonel', 'colonel__instance'
        ):
            if interface.colonel.instance not in request.user.instances:
                continue
            if not interface.colonel.is_connected:
                continue
            interface.broadcast_reset()
            broadcasted += 1

        if broadcasted:
            self.message_user(
                request,
                f"Reset and clear-address command was broadcast to "
                f"{broadcasted} interfaces."
            )
        else:
            self.message_user(
                request,
                f"No reset command was broadcast, "
                f"probably because they are out of reach at the moment."
            )

    broadcast_reset.short_description = (
        "DALI danger: RESET and clear short addresses"
    )
