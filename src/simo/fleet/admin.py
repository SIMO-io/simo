from django.contrib import admin
from django.utils.safestring import mark_safe
from django.template.loader import render_to_string
from django.templatetags.static import static
from simo.core.models import Component
from simo.core.utils.admin import FormAction
from .models import Colonel, I2CInterface
from .forms import ColonelAdminForm, MoveColonelForm, I2CInterfaceAdminForm


class I2CInterfaceInline(admin.TabularInline):
    model = I2CInterface
    extra = 0
    form = I2CInterfaceAdminForm


@admin.register(Colonel)
class ColonelAdmin(admin.ModelAdmin):
    form = ColonelAdminForm
    list_display = (
        '__str__', 'instance', 'type', 'connected', 'last_seen', 'firmware_version',
        'newer_firmware_available', 'is_authorized'
    )
    readonly_fields = (
        'type', 'uid', 'connected', 'last_seen',
        'firmware_version', 'newer_firmware_available', 'occupied_pins',
        'components_display', 'is_authorized'
    )
    # inlines = ColonelComponentInline, ColonelBLEDeviceInline
    fields = (
        'name', 'instance', 'enabled', 'firmware_auto_update'
    ) + readonly_fields + ('pwm_frequency', 'logs_stream', 'log', )

    actions = (
        'update_firmware', 'check_for_upgrade', 'update_config', 'restart',
        FormAction(MoveColonelForm, 'move_colonel_to', "Move to other Colonel")
    )

    inlines = I2CInterfaceInline,

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_master:
            return qs
        return qs.filter(instance__in=request.user.instances)


    def components_display(self, obj=None):
        resp = ''
        for pin_no, item in obj.occupied_pins.items():
            try:
                component = Component.objects.get(pk=item)
            except:
                continue
            resp += '<a href="%s" target=_blank>%s</a><br>' % (
                component.get_admin_url(), str(component)
            )
        return mark_safe(resp)
    components_display.short_description = 'Components'

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        res = super().save_model(request, obj, form, change)
        obj.restart()
        return res

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
        if form.cleaned_data['colonel'] not in request.user.instances:
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

    def connected(self, obj):
        if obj.is_connected:
            return mark_safe('<img src="%s" alt="True">' % static('admin/img/icon-yes.svg'))
        return mark_safe('<img src="%s" alt="False">' % static('admin/img/icon-no.svg'))




# @admin.register(BLEDevice)
# class BLEDeviceAdmin(admin.ModelAdmin):
#     list_display = ['name', 'mac', 'type', 'last_seen']
#     readonly_fields = list_display + ['addr']
#     fields = readonly_fields
