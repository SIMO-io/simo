import os
import traceback
import requests
from dal import forward
from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm as OrgAdminAuthenticationForm
from django.db import models
from django import forms
from django.forms import formset_factory
from django.conf import settings
from django.urls.base import get_script_prefix
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.models import ContentType
from timezone_utils.choices import ALL_TIMEZONES_CHOICES
from dal import autocomplete
from .models import (
    Icon, Category, Gateway, Component
)
from .widgets import LocationWidget
from simo.conf import dynamic_settings
from .widgets import SVGFileWidget, PythonCode, LogOutputWidget
from .widgets import ImageWidget
from .utils.helpers import get_random_string
from .utils.formsets import FormsetField
from .utils.validators import validate_slaves


class HubConfigForm(forms.Form):
    name = forms.CharField(
        label=_("Hub Name"), required=True,
        widget=forms.TextInput(attrs={'placeholder': "Home Sweet Home"})
    )
    uid = forms.CharField(
        label=_('Unique Identifier (UID)'), required=False,
        widget=forms.TextInput(attrs={'placeholder': "Df5Hd8v1"}),
        help_text="Leave blank if this is a new instance."
    )
    time_zone = forms.ChoiceField(
        label=_("Time zone"), required=True,
        choices=ALL_TIMEZONES_CHOICES
    )
    units_of_measure = forms.ChoiceField(
        label=_("Units of Measure"), required=True,
        choices=(('metric', 'Metric'), ('imperial', 'Imperial'))
    )
    cover_image = forms.FileField(
        label=_("Cover image"), required=True, widget=ImageWidget
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        post_data = cleaned_data.copy()
        post_data.pop('cover_image')
        if not dynamic_settings['core__hub_secret']:
            dynamic_settings['core__hub_secret'] = get_random_string(20)
        post_data['secret'] = dynamic_settings['core__hub_secret']
        post_data['email'] = self.user.email
        try:
            resp = requests.post(
                'https://simo.io/hubs/sync-initial-config/', json=post_data,
            )
        except Exception as e:
            raise forms.ValidationError(
                "Connection error. "
                "Make sure your hub can reach https://simo.io and try again."
            )

        if resp.status_code == 400:
            resp_json = resp.json()
            resp_json.pop('status', None)
            for field_name, msg in resp_json.items():
                self.add_error(field_name, msg)
        elif resp.status_code == 200:
            cleaned_data['uid'] = resp.json()['uid']
        else:
            raise forms.ValidationError(
                "Bad response from https://simo.io. Please try again. "
            )
        return cleaned_data


class CoordinatesForm(forms.Form):
    location = forms.CharField(
        label=_("Where is your hub located?"),
        widget=LocationWidget(based_fields=[])
    )
    share_location = forms.BooleanField(
        label="Share exact location with SIMO.io for "
              "better accuracy of location related services.",
        required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial['location']:
            self.fields['location'].widget = LocationWidget(
                based_fields=[], zoom=2
            )




class TermsAndConditionsForm(forms.Form):
    accept = forms.BooleanField(required=False)

    def clean_accept(self):
        if not self.cleaned_data['accept']:
            raise forms.ValidationError(_("You must accept SIMO.io Terms & Conditions if you want to continue."))
        return self.cleaned_data['accept']


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

    def __init__(self, gateway, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if gateway:
            from .utils.type_constants import get_controller_types_choices
            self.fields['controller_type'].choices = get_controller_types_choices(
                gateway
            )


class ComponentAdminForm(forms.ModelForm):
    gateway = None
    controller_type = None
    has_icon = True
    has_alarm = True

    class Meta:
        model = Component
        fields = '__all__'
        exclude = (
            'gateway', 'controller_uid', 'base_type',
            'alive', 'value_type', 'value', 'arm_status',
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
            'instance_methods': PythonCode
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        self.controller_uid = kwargs.pop('controller_uid', '')
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.gateway = self.instance.gateway
            self.controller = self.instance.controller
        else:
            from .utils.type_constants import get_controller_types_map
            ControllerClass = get_controller_types_map().get(self.controller_uid)
            if ControllerClass:
                self.controller = ControllerClass(self.instance)
                self.gateway = Gateway.objects.filter(
                    type=ControllerClass.gateway_class.uid
                ).first()
                self.instance.gateway = self.gateway
                self.instance.controller_uid = ControllerClass.uid
                self.instance.base_type = self.controller.base_type
                self.instance.value = self.controller.default_value
                self.instance.value_previous = self.controller.default_value
                self.instance.config = self.controller.default_config
                self.instance.meta = self.controller.default_meta

    @classmethod
    def get_admin_fieldsets(cls, request, obj=None):
        main_fields = (
            'name', 'icon', 'zone', 'category',
            'show_in_app', 'battery_level',
            'instance_methods', 'value_units',
            'alarm_category', 'arm_status',
        )
        base_fields = ['id', 'gateway', 'base_type', 'name']
        if cls.has_icon:
            base_fields.append('icon')

        base_fields.append('zone')
        base_fields.append('category')

        for field_name in cls.declared_fields:
            if field_name not in main_fields:
                base_fields.append(field_name)

        base_fields.append('show_in_app')
        base_fields.append('control')
        base_fields.append('instance_methods')

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
                    'alive', 'battery_level',
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

    def clean_slaves(self):
        if not self.cleaned_data['slaves'] or not self.instance:
            return self.cleaned_data['slaves']
        return validate_slaves(self.cleaned_data['slaves'], self.instance)


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

    def clean_slaves(self):
        if not self.cleaned_data['slaves'] or not self.instance:
            return self.cleaned_data['slaves']
        return validate_slaves(self.cleaned_data['slaves'], self.instance)


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


class RGBWConfigForm(BaseComponentForm):
    has_white = forms.BooleanField(
        label=_("Has WHITE color channel"), required=False,
    )