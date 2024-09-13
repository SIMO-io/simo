import traceback
from dal import forward
from django.contrib.admin.forms import AdminAuthenticationForm as OrgAdminAuthenticationForm
from django.db import models
from django import forms
from django.forms import formset_factory
from django.urls.base import get_script_prefix
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.models import ContentType
from actstream import action
from dal import autocomplete
from .models import (
    Icon, Category, Gateway, Component
)
from .widgets import SVGFileWidget, LogOutputWidget
from .utils.formsets import FormsetField
from .utils.validators import validate_slaves


class HiddenField(forms.CharField):
    '''
        Hidden field used in API
    '''
    def __init__(self, *args, **kwargs):
        super().__init__(widget=forms.HiddenInput(), *args, **kwargs)


class AdminAuthenticationForm(OrgAdminAuthenticationForm):

    def confirm_login_allowed(self, user):
        if not user.is_active:
            raise forms.ValidationError(
                self.error_messages['inactive'],
                code='inactive',
            )
        if not user.is_superuser:
            raise forms.ValidationError(
                self.error_messages['invalid_login'],
                code='invalid_login',
                params={'username': self.username_field.verbose_name}
            )


class IconForm(forms.ModelForm):

    class Meta:
        model = Icon
        fields = '__all__'
        widgets = {
            'default': SVGFileWidget, 'active': SVGFileWidget,
        }



class CategoryAdminForm(forms.ModelForm):

    class Meta:
        model = Category
        fields = '__all__'
        widgets = {
            'icon': autocomplete.ModelSelect2(
                url='autocomplete-icon', attrs={'data-html': True}
            )
        }



class ConfigFieldsMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model_fields = [
            f.name for f in Component._meta.fields
        ] + ['slaves', ]
        self.config_fields = []
        for field_name, field in self.fields.items():
            if field_name in self.model_fields:
                continue
            self.config_fields.append(field_name)
        if self.instance.pk:
            for field_name in self.config_fields:
                if field_name not in self.instance.config:
                    continue
                if hasattr(self.fields[field_name], 'queryset'):
                    if isinstance(self.instance.config.get(field_name), list):
                        self.fields[field_name].initial = \
                            self.fields[field_name].queryset.filter(
                                pk__in=self.instance.config.get(field_name)
                            )
                    else:
                        self.fields[field_name].initial = \
                            self.fields[field_name].queryset.filter(
                                pk=self.instance.config.get(field_name)
                            ).first()
                else:
                    self.fields[field_name].initial = \
                        self.instance.config.get(field_name)

    def save(self, commit=True):
        for field_name in self.config_fields:
            # support for partial forms
            if field_name not in self.cleaned_data:
                continue
            if isinstance(self.cleaned_data[field_name], models.Model):
                self.instance.config[field_name] = \
                    self.cleaned_data[field_name].pk
            elif isinstance(self.cleaned_data[field_name], models.QuerySet):
                self.instance.config[field_name] = [
                    obj.pk for obj in self.cleaned_data[field_name]
                ]
            else:
                self.instance.config[field_name] = \
                    self.cleaned_data[field_name]

        if commit:
            from simo.users.middleware import get_current_user
            actor = get_current_user()
            if self.instance.pk:
                verb = 'modified'
            else:
                verb = 'created'
            action.send(
                actor, target=self.instance, verb=verb,
                instance_id=self.instance.zone.instance.id,
                action_type='management_event'
            )

        return super().save(commit)


class BaseGatewayForm(ConfigFieldsMixin, forms.ModelForm):
    log = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Gateway
        fields = '__all__'
        exclude = 'type', 'config', 'status',

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            prefix = get_script_prefix()
            if prefix == '/':
                prefix = ''
            self.fields['log'].widget = LogOutputWidget(
                prefix + '/ws/log/%d/%d/' % (
                    ContentType.objects.get_for_model(Gateway).id,
                    self.instance.id
                )
            )

    @classmethod
    def get_admin_fieldsets(cls, request, obj=None):
        main_fields = (
            'type', 'control', 'log'
        )
        fields = ['type']
        for field_name in cls.base_fields:
            if field_name not in main_fields:
                fields.append(field_name)
        fields.extend(['control', 'log'])
        return [('', {'fields': fields})]


class GatewayTypeSelectForm(forms.Form):
    type = forms.ChoiceField(choices=())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .utils.type_constants import get_gateway_choices
        self.fields['type'].choices = get_gateway_choices()


class GatewaySelectForm(forms.Form):
    gateway = forms.ModelChoiceField(Gateway.objects.all())

    def __init__(self, *args, **kwargs):
        queryset = kwargs.pop('queryset', None)
        super().__init__(*args, **kwargs)
        if queryset:
            self.fields['gateway'].queryset = queryset


class CompTypeSelectForm(forms.Form):
    controller_type = forms.ChoiceField(choices=())

    def __init__(self, gateway, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if gateway:
            from .utils.type_constants import (
                GATEWAYS_MAP, get_controller_types_map
            )

            CONTROLLERS_BY_GATEWAY = {}
            for gateway_slug, gateway_cls in GATEWAYS_MAP.items():
                CONTROLLERS_BY_GATEWAY[gateway_slug] = {}
                for ctrl_uid, ctrl_cls in get_controller_types_map(
                    gateway_cls, user=request.user
                ).items():
                    CONTROLLERS_BY_GATEWAY[gateway_slug][ctrl_uid] = ctrl_cls

            self.fields['controller_type'].choices = [
                (cls.uid, cls.name) for cls in CONTROLLERS_BY_GATEWAY.get(
                    gateway.handler.uid, {}
                ).values() if cls.manual_add
            ]


class ComponentAdminForm(forms.ModelForm):
    gateway = None
    controller_type = None
    has_icon = True
    has_alarm = True

    # fields that can be edited via SIMO.io app by instance owners.
    # Users who have is_owner enabled on their user role.
    basic_fields = ['name', 'icon', 'zone', 'category', 'show_in_app']

    class Meta:
        model = Component
        fields = (
            'name', 'icon', 'zone', 'category', 'show_in_app', 'notes',
            'alarm_category'
        )
        widgets = {
            'icon': autocomplete.ModelSelect2(
                url='autocomplete-icon', attrs={'data-html': True}
            ),
            'zone': autocomplete.ModelSelect2(
                url='autocomplete-zone', attrs={'data-html': True}
            ),
            'category': autocomplete.ModelSelect2(
                url='autocomplete-category', attrs={'data-html': True}
            ),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        self.controller_uid = kwargs.pop('controller_uid', '')
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.gateway = self.instance.gateway
            self.controller = self.instance.controller
        else:
            from .utils.type_constants import CONTROLLER_TYPES_MAP
            ControllerClass = CONTROLLER_TYPES_MAP.get(self.controller_uid)
            if ControllerClass:
                self.controller = ControllerClass(self.instance)
                self.gateway = Gateway.objects.filter(
                    type=ControllerClass.gateway_class.uid
                ).first()
                self.instance.gateway = self.gateway
                self.instance.controller_uid = ControllerClass.uid
                self.instance.base_type = self.controller.base_type
                self.instance.value = self.controller.default_value
                self.instance.value_units = self.controller.default_value_units
                self.instance.value_previous = self.controller.default_value
                self.instance.config = self.controller.default_config
                self.instance.meta = self.controller.default_meta

        self.cleanup_missing_keys(kwargs.get("data"))

    def cleanup_missing_keys(self, data):
        """
        Removes missing keys from fields on form submission.
        This avoids resetting fields that are not present in
        the submitted data, which may be the sign of a buggy
        or incomplete template.
        Note that this cleanup relies on the HTML form being
        patched to send all keys, even for checkboxes, via
        input[type="hidden"] fields or some JS magic.
        """
        if data is None:
            # not a form submission, don't modify self.fields
            return

        got_keys = list(data.keys())
        formset_fields = set()
        for key in got_keys:
            if key.endswith('-TOTAL_FORMS'):
                formset_fields.add(key[:-12])
        got_keys.extend(list(formset_fields))
        field_names = self.fields.keys()
        for missing in set(field_names) - set(got_keys):
            del self.fields[missing]

    @classmethod
    def get_admin_fieldsets(cls, request, obj=None):
        main_fields = (
            'name', 'icon', 'zone', 'category',
            'show_in_app', 'battery_level',
            #'instance_methods',
            'value_units',
            'alarm_category', 'arm_status',
            'notes'
        )
        base_fields = ['id', 'gateway', 'base_type', 'info', 'name']
        if cls.has_icon:
            base_fields.append('icon')

        base_fields.append('zone')
        base_fields.append('category')

        for field_name in cls.declared_fields:
            if field_name not in main_fields:
                base_fields.append(field_name)

        base_fields.append('show_in_app')
        base_fields.append('control')
        base_fields.append('notes')

        fieldsets = [
            (_("Base settings"), {'fields': base_fields}),
        ]
        if cls.has_alarm:
            fieldsets.append(
                (_("Alarm"), {
                    'fields': (
                        'alarm_category', 'arm_status'
                    ),
                    'classes': ('collapse',),
                })
            )
        fieldsets.extend([
            (_("Meta"), {
                'fields': (
                    'alive', 'error_msg', 'battery_level',
                    'config', 'meta',
                    'value', 'value_units',
                    'history'
                ),
                'classes': ('collapse',),
            }),
        ])
        return fieldsets

    def clean_category(self):
        if not self.cleaned_data['category']:
            return
        if self.cleaned_data['category'].all:
            raise forms.ValidationError(_(
                "This is generic category where all components belong anyway. "
                "Please choose something more specific."
            ))
        return self.cleaned_data['category']

    def clean_instance_methods(self):
        custom_methods = {}
        try:
            # need new line at the beginning to display correct
            # line numbering in an event of exception
            exec(
                '\n' + self.cleaned_data['instance_methods'],
                None, custom_methods
            )
        except Exception:
            error = traceback.format_exc()
            error = error[error.find('File') + 5:]
            error = error[error.find('File'):]
            error = error.replace('\n', '<br>').replace(' ', '&nbsp;')
            raise forms.ValidationError(mark_safe(error))
        return self.cleaned_data['instance_methods']


class BaseComponentForm(ConfigFieldsMixin, ComponentAdminForm):
    pass


class ValueLimitForm(forms.Form):
    value = forms.FloatField()
    name = forms.CharField(max_length=10)

    prefix = 'limits'


class ValueLimitsMixin:

    limits = FormsetField(
        formset_factory(
            ValueLimitForm, can_delete=True, can_order=True, extra=0, max_num=3
        )
    )


class NumericSensorForm(BaseComponentForm):
    widget = forms.ChoiceField(
        initial='numeric-sensor', choices=(
            ('numeric-sensor', "Basic Sensor"),
            ('numeric-sensor-graph', "Graph"),
        )
    )
    limits = FormsetField(
        formset_factory(
            ValueLimitForm, can_delete=True, can_order=True, extra=0, max_num=3
        ), label="Graph Limits"
    )
    value_units = forms.CharField(required=False)


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['value_units'].initial = self.controller.default_value_units



class MultiSensorConfigForm(BaseComponentForm):
    icon_1 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_2 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_3 = forms.ModelChoiceField(
        queryset=Icon.objects.all(), required=False,
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_4 = forms.ModelChoiceField(
        queryset=Icon.objects.all(), required=False,
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_5 = forms.ModelChoiceField(
        queryset=Icon.objects.all(), required=False,
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_6 = forms.ModelChoiceField(
        queryset=Icon.objects.all(), required=False,
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_7 = forms.ModelChoiceField(
        queryset=Icon.objects.all(), required=False,
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_8 = forms.ModelChoiceField(
        queryset=Icon.objects.all(), required=False,
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    has_icon = False


class SwitchForm(BaseComponentForm):
    slaves = forms.ModelMultipleChoiceField(
        required=False,
        queryset=Component.objects.filter(
            base_type__in=(
                'dimmer', 'switch', 'blinds', 'script'
            )
        ),
        widget=autocomplete.ModelSelect2Multiple(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(forward.Const(
                ['dimmer', 'switch', 'blinds', 'script'], 'base_type'),
            )
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['slaves'].initial = self.instance.slaves.all()

    def clean_slaves(self):
        if not self.cleaned_data['slaves'] or not self.instance:
            return self.cleaned_data['slaves']
        return validate_slaves(self.cleaned_data['slaves'], self.instance)

    def save(self, commit=True):
        obj = super().save(commit=commit)
        if commit and 'slaves' in self.cleaned_data:
            obj.slaves.set(self.cleaned_data['slaves'])
        return obj


class DoubleSwitchConfigForm(BaseComponentForm):
    icon_1 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_2 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    has_icon = False


class TrippleSwitchConfigForm(BaseComponentForm):
    icon_1 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_2 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_3 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    has_icon = False


class QuadrupleSwitchConfigForm(BaseComponentForm):
    icon_1 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_2 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_3 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_4 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    has_icon = False


class QuintupleSwitchConfigForm(BaseComponentForm):
    icon_1 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_2 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_3 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_4 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    icon_5 = forms.ModelChoiceField(
        queryset=Icon.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-icon', attrs={'data-html': True}
        )
    )
    has_icon = False


class DimmerConfigForm(BaseComponentForm):
    min = forms.FloatField(
        initial=0.0, help_text="Minimum component value."
    )
    max = forms.FloatField(
        initial=1.0, help_text="Maximum component value."
    )
    value_units = forms.CharField(required=False)
    inverse = forms.BooleanField(
        label=_("Inverse dimmer signal"), required=False
    )
    slaves = forms.ModelMultipleChoiceField(
        required=False,
        queryset=Component.objects.filter(
            base_type__in='dimmer',
        ),
        widget=autocomplete.ModelSelect2Multiple(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(forward.Const(['dimmer', ], 'base_type'),)
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['value_units'].initial = self.controller.default_value_units
        if self.instance.pk:
            self.fields['slaves'].initial = self.instance.slaves.all()

    def clean_slaves(self):
        if not self.cleaned_data['slaves'] or not self.instance:
            return self.cleaned_data['slaves']
        return validate_slaves(self.cleaned_data['slaves'], self.instance)

    def save(self, commit=True):
        obj = super().save(commit=commit)
        if commit:
            obj.slaves.set(self.cleaned_data['slaves'])
        return obj


class DimmerPlusConfigForm(BaseComponentForm):
    main_min = forms.FloatField(
        initial=0.0, help_text="Minimum main value."
    )
    main_max = forms.FloatField(
        initial=1.0, help_text="Maximum main value."
    )
    secondary_min = forms.FloatField(
        initial=0.0, help_text="Minimum secondary value."
    )
    secondary_max = forms.FloatField(
        initial=1.0, help_text="Maximum secondary value."
    )
    value_units = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['value_units'].initial = self.controller.default_value_units


class RGBWConfigForm(BaseComponentForm):
    has_white = forms.BooleanField(
        label=_("Has WHITE color channel"), required=False,
    )