import markdown
from django.utils.translation import gettext_lazy as _
from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe
from easy_thumbnails.fields import ThumbnailerField
from adminsortable2.admin import SortableAdminMixin
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django.shortcuts import redirect, render
from simo.users.models import ComponentPermission
from simo.core.utils.admin import EasyObjectsDeleteMixin
from .utils.type_constants import (
    ALL_BASE_TYPES, GATEWAYS_MAP, CONTROLLERS_BY_GATEWAY
)
from .models import Instance, Icon, Gateway, Component, Zone, Category
from .forms import (
    GatewayTypeSelectForm,
    IconForm, CategoryAdminForm,
    GatewaySelectForm, BaseGatewayForm,
    CompTypeSelectForm,
    BaseComponentForm
)
from .filters import ZonesFilter
from .widgets import AdminImageWidget
from simo.conf import dynamic_settings

csrf_protect_m = method_decorator(csrf_protect)


@admin.register(Icon)
class IconAdmin(EasyObjectsDeleteMixin, admin.ModelAdmin):
    form = IconForm
    list_display = 'slug', 'preview', 'copyright'
    search_fields = 'slug', 'keywords',

    def has_module_permission(self, request):
        return request.user.is_master

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def preview(self, obj):
        if not obj:
            return ''
        return render_to_string(
            'admin/core/icon_preview.html',
            {'icon': obj}
        )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = self.readonly_fields
        if obj:
            readonly_fields += 'slug', 'copyright'
        return readonly_fields



@admin.register(Zone)
class ZoneAdmin(EasyObjectsDeleteMixin, SortableAdminMixin, admin.ModelAdmin):
    list_display = 'name', 'instance'
    search_fields = 'name',
    list_filter = 'instance',

    def get_fields(self, request, obj=None):
        if request.user.is_master:
            return super().get_fields(request, obj)
        fields = []
        for field in super().get_fields(request, obj):
            if field != 'instance':
                fields.append(field)
        return fields


@admin.register(Category)
class CategoryAdmin(EasyObjectsDeleteMixin, SortableAdminMixin, admin.ModelAdmin):
    form = CategoryAdminForm
    list_display = 'name_display', 'all'
    search_fields = 'name',
    autocomplete_fields = 'icon',

    formfield_overrides = {
        ThumbnailerField: {'widget': AdminImageWidget},
    }

    def name_display(self, obj):
        if not obj:
            return ''
        return render_to_string('admin/item_name_display.html', {'obj': obj})
    name_display.short_description = _("name")

    def has_module_permission(self, request):
        return request.user.is_master

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)


@admin.register(Gateway)
class GatewayAdmin(EasyObjectsDeleteMixin, admin.ModelAdmin):
    list_display = 'type', 'status'
    readonly_fields = ('type', 'control')

    def has_module_permission(self, request):
        return request.user.is_master

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def add_view(self, request, *args, **kwargs):

        if request.method == 'POST' and 'prev' in request.POST:
            if request.session.get('gateway_type'):
                request.session.pop('gateway_type')
            return redirect(request.path)

        ctx = {
            **self.admin_site.each_context(request),
            'view': self, 'opts': Gateway._meta,
            'add': True,
            'change': False,
            'is_popup': False,
            'save_as': False,
            'has_editable_inline_admin_formsets': False,
            'has_view_permission': True,
            'has_delete_permission': False,
            'has_add_permission': False,
            'has_change_permission': False,
            'is_last': False, 'is_first': True, 'total_steps': 3,
            'current_step': 1
        }
        if request.session.get('gateway_type'):
            try:
                formClass = GATEWAYS_MAP.get(
                    request.session.get('gateway_type')
                ).config_form
            except:
                request.session.pop('gateway_type')
                return redirect(request.path)

            ctx['is_first'] = False
            ctx['current_step'] = 2

            ctx['is_last'] = True

            if request.method == 'POST':
                ctx['form'] = formClass(
                    data=request.POST, files=request.FILES,
                )
                if ctx['form'].is_valid():
                    new_gateway = ctx['form'].save(commit=False)
                    new_gateway.type = request.session.pop('gateway_type')
                    new_gateway.save()
                    return redirect(new_gateway.get_admin_url())
            else:
                ctx['form'] = formClass()
            ctx['form'].fields.pop('log')

            if not ctx['form'].fields:
                try:
                    new_gateway = Gateway.objects.create(
                        type=request.session.get('gateway_type')
                    )
                except:
                    ctx['error'] = '%s gateway already exists!' \
                                   % GATEWAYS_MAP.get(
                        request.session.get('gateway_type'), 'None'
                    ).name
                else:
                    request.session.pop('gateway_type')
                    return redirect(new_gateway.get_admin_url())

        else:
            if request.method == 'POST':
                ctx['form'] = GatewayTypeSelectForm(data=request.POST)
                if ctx['form'].is_valid():
                    request.session['gateway_type'] = ctx['form'].cleaned_data['type']
                    return redirect(request.path)
            else:
                ctx['form'] = GatewayTypeSelectForm()

        return render(
            request, 'admin/wizard/wizard_add.html', ctx
        )

    def get_form(self, request, obj=None, change=False, **kwargs):
        if obj:
            gateway_class = GATEWAYS_MAP.get(obj.type)
            if gateway_class:
                return gateway_class.config_form
        return BaseGatewayForm

    def get_fieldsets(self, request, obj=None):
        form = self._get_form_for_get_fields(request, obj)
        return form.get_admin_fieldsets(request, obj)


    def control(self, obj):
        try:
            return render_to_string(
                'admin/gateway_control/widget.html', {
                    'obj': obj, 'global_preferences': dynamic_settings
                }
            )
        except:
            return ''


class ComponentPermissionInline(admin.TabularInline):
    model = ComponentPermission
    extra = 0
    readonly_fields = 'role',
    fields = 'role', 'read', 'write'

    def get_queryset(self, request):
        qs = super().get_queryset(request).exclude(role__is_superuser=True)
        if request.user.is_master:
            return qs
        # component permission objects should not be created for other
        # instances than component belongs to, but we add this
        # as a double safety measure.
        return qs.filter(role__instance__in=request.user.instances)


    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Component)
class ComponentAdmin(EasyObjectsDeleteMixin, admin.ModelAdmin):
    form = BaseComponentForm
    list_display = (
        'id', 'name_display', 'value_display', 'base_type', 'alive', 'battery_level',
        'alarm_category', 'show_in_app',
    )
    readonly_fields = (
        'id', 'controller_uid', 'base_type', 'info', 'gateway', 'config',
        'alive', 'error_msg', 'battery_level',
        'control', 'value', 'arm_status', 'history', 'meta'
    )
    list_filter = (
        'gateway', 'base_type', ('zone', ZonesFilter), 'category', 'alive',
        'alarm_category', 'arm_status'
    )

    search_fields = 'id', 'name', 'value', 'config', 'meta', 'notes'
    list_per_page = 100
    change_list_template = 'admin/component_change_list.html'
    inlines = ComponentPermissionInline,
    # standard django admin change_form.html template + adds side panel
    # for displaying component controller info.
    #change_form_template = 'admin/core/component_change_form.html'

    def has_change_permission(self, request, obj=None):
        if not obj or not obj.controller or not obj.controller.masters_only:
            return True
        return request.user.is_master

    def get_fieldsets(self, request, obj=None):
        form = self._get_form_for_get_fields(request, obj)
        fieldsets = form.get_admin_fieldsets(request, obj)
        if not request.user.is_master:
            for section, fields_map in fieldsets:
                fields_map.pop('instance_methods', None)
        return fieldsets

    def add_view(self, request, *args, **kwargs):

        if request.method == 'POST' and 'prev' in request.POST:
            if request.session.get('add_comp_type'):
                request.session.pop('add_comp_type')
            elif request.session.get('add_comp_gateway'):
                request.session.pop('add_comp_gateway')
            return redirect(request.path)

        ctx = {
            **self.admin_site.each_context(request),
            'view': self, 'opts': Component._meta,
            'add': True,
            'change': False,
            'is_popup': False,
            'save_as': False,
            'has_editable_inline_admin_formsets': False,
            'has_view_permission': True,
            'has_delete_permission': False,
            'has_add_permission': False,
            'has_change_permission': False,
            'is_last': False, 'is_first': True, 'total_steps': 3,
            'current_step': 1
        }
        if request.session.get('add_comp_gateway'):
            try:
                gateway = Gateway.objects.get(
                    pk=request.session['add_comp_gateway']
                )
            except:
                request.session.pop('add_comp_gateway')
                return redirect(request.path)

            ctx['is_first'] = False
            ctx['current_step'] = 2
            ctx['selected_gateway'] = gateway

            if request.session.get('add_comp_type'):
                try:
                    controller_cls = CONTROLLERS_BY_GATEWAY.get(
                        gateway.type, {}
                    )[request.session['add_comp_type']]
                except:
                    request.session.pop('add_comp_type')
                    return redirect(request.path)

                add_form = controller_cls.add_form

                def pop_fields_from_form(form):
                    for field_neme in (
                        'value_units', 'show_in_app', 'instance_methods',
                        'alarm_category', 'arm_status'
                    ):
                        if field_neme in form.fields:
                            form.fields.pop(field_neme, None)
                    if 'slaves' not in form.declared_fields:
                        form.fields.pop('slaves', None)

                ctx['is_last'] = True
                ctx['current_step'] = 3
                ctx['selected_type'] = ALL_BASE_TYPES.get(
                    controller_cls.base_type, controller_cls.base_type
                )
                ctx['info'] = controller_cls.info(controller_cls)
                if request.method == 'POST':
                    ctx['form'] = add_form(
                        request=request,
                        controller_uid=controller_cls.uid,
                        data=request.POST, files=request.FILES,
                        initial=request.session.get('c_add_init'),
                    )
                    pop_fields_from_form(ctx['form'])
                    if ctx['form'].is_valid():
                        if ctx['form'].controller.is_discoverable:
                            ctx['form'].controller.init_discovery(
                                ctx['form'].cleaned_data
                            )
                            ctx['discovery_msg'] = ctx['form'].controller.discovery_msg
                            instance = ctx['form'].cleaned_data['zone'].instance
                            ctx['api_check_url'] = reverse(
                                'discoveries-list',
                                kwargs={'instance_slug': instance.slug}
                            ) + f"?controller_uid={ctx['form'].controller.uid}"
                            ctx['api_retry_url'] = reverse(
                                'discoveries-list',
                                kwargs={'instance_slug': instance.slug}
                            ) + f"retry/?controller_uid={ctx['form'].controller.uid}"
                            ctx['api_components_url'] = reverse(
                                'components-list',
                                kwargs={'instance_slug': instance.slug}
                            )
                            return render(
                                request, 'admin/wizard/discovery.html', ctx
                            )
                        new_comp = ctx['form'].save()
                        request.session.pop('add_comp_gateway')
                        request.session.pop('add_comp_type')
                        return redirect(new_comp.get_admin_url())
                else:
                    ctx['form'] = add_form(
                        request=request,
                        controller_uid=controller_cls.uid,
                        initial=request.session.get('c_add_init'),
                    )
                    pop_fields_from_form(ctx['form'])

            else:
                if request.method == 'POST':
                    ctx['form'] = CompTypeSelectForm(gateway, request, data=request.POST)
                    if ctx['form'].is_valid():
                        request.session['add_comp_type'] = \
                            ctx['form'].cleaned_data['controller_type']
                        return redirect(request.path)

                else:
                    ctx['form'] = CompTypeSelectForm(gateway, request)
        else:
            if request.method == 'POST':
                ctx['form'] = GatewaySelectForm(data=request.POST)
                if ctx['form'].is_valid():
                    request.session['add_comp_gateway'] = \
                        ctx['form'].cleaned_data['gateway'].pk
                    return redirect(request.path)
            else:
                ctx['form'] = GatewaySelectForm()

        return render(
            request, 'admin/wizard/wizard_add.html', ctx
        )

    def change_view(self, request, *args, **kwargs):
        if request.session.get('add_comp_type'):
            request.session.pop('add_comp_type')
        elif request.session.get('add_comp_gateway'):
            request.session.pop('add_comp_gateway')
        return super().change_view(request, *args, **kwargs)

    def changelist_view(self, request, extra_context=None):
        if request.session.get('add_comp_type'):
            request.session.pop('add_comp_type')
        elif request.session.get('add_comp_gateway'):
            request.session.pop('add_comp_gateway')
        return super().changelist_view(request, extra_context=extra_context)

    def get_form(self, request, obj=None, change=False, **kwargs):
        if obj:
            try:
                self.form = CONTROLLERS_BY_GATEWAY.get(
                    obj.gateway.type, {}
                )[obj.controller_uid].config_form
            except KeyError:
                pass

        AdminForm = super().get_form(request, obj=obj, change=change, **kwargs)

        class AdminFormWithRequest(AdminForm):
            def __new__(cls, *args, **kwargs):
                kwargs['request'] = request
                return AdminForm(*args, **kwargs)

        return AdminFormWithRequest

    def save_model(self, request, obj, form, change):
        form.save()

    def value_display(self, obj):
        if not obj.pk:
            return ''
        val = str(obj.value)
        if len(val) > 10:
            val = val[:10] + '...'
        return val
    value_display.short_description = _("value")

    def name_display(self, obj):
        if not obj:
            return ''
        return render_to_string(
            'admin/item_name_display.html', {
                'obj': obj,
            }
        )
    name_display.short_description = _("name")

    def control(self, obj):
        return render_to_string(
            obj.controller.admin_widget_template, {
                'obj': obj, 'global_preferences': dynamic_settings
            }
        )

    def info(self, obj):
        if not obj.controller:
            return
        info = obj.controller.info()
        if not info:
            return
        return mark_safe(
            f'<div class="markdownified-info">'
            f'{markdown.markdown(info)}'
            f'</div>'
        )

    def history(self, obj):
        if not obj:
            return ''
        return render_to_string(
            'admin/component_history.html', {
                'value_history': obj.history.filter(type='value').order_by('-date')[:50],
                'arm_status_history': obj.history.filter(type='security').order_by('-date')[:50]
            }
        )