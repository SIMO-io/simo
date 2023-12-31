from django import forms
from django.forms import formset_factory
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.urls.base import get_script_prefix
from django.contrib.contenttypes.models import ContentType
from simo.core.forms import BaseComponentForm
from simo.core.models import Icon, Component
from simo.core.controllers import (
    BinarySensor, NumericSensor, MultiSensor, Switch
)
from simo.core.widgets import PythonCode, LogOutputWidget
from dal import autocomplete, forward
from simo.core.utils.config_values import config_to_dict
from simo.core.utils.formsets import FormsetField
from simo.core.utils.helpers import get_random_string
from simo.core.utils.form_fields import AutocompleteSelect2
from simo.conf import dynamic_settings


class ScriptConfigForm(BaseComponentForm):
    autostart = forms.BooleanField(
        initial=True, required=False,
        help_text="Auto start my script on system boot."
    )
    autorestart = forms.BooleanField(
        initial=True, required=False,
        help_text="Wake my script up automatically if it encounters error."
    )
    code = forms.CharField(widget=PythonCode)
    log = forms.CharField(
        widget=forms.HiddenInput, required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            prefix = get_script_prefix()
            if prefix == '/':
                prefix = ''
            self.fields['log'].widget = LogOutputWidget(
                prefix + '/ws/log/%d/%d/' % (
                    ContentType.objects.get_for_model(Component).id,
                    self.instance.id
                )
            )

    @classmethod
    def get_admin_fieldsets(cls, request, obj=None):
        base_fields = (
            'id', 'gateway', 'base_type', 'name', 'icon', 'zone', 'category',
            'tags', 'show_in_app', 'autostart', 'autorestart',
            'code', 'control', 'log'
        )

        fieldsets = [
            (_("Base settings"), {'fields': base_fields}),
            (_("History"), {
                'fields': ('history',),
                'classes': ('collapse',),
            }),
        ]
        return fieldsets


class ThermostatConfigForm(BaseComponentForm):
    temperature_sensor = forms.ModelChoiceField(
        Component.objects.filter(
            base_type__in=(
                NumericSensor.base_type,
                MultiSensor.base_type
            )
        ),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const([
                    NumericSensor.base_type,
                    MultiSensor.base_type
                ], 'base_type'),
            )
        )
    )
    heater = forms.ModelChoiceField(
        Component.objects.filter(base_type=Switch.base_type),
        required=False, widget=autocomplete.ModelSelect2(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const([
                    Switch.base_type,
                ], 'base_type'),
            )
        )
    )
    cooler = forms.ModelChoiceField(
        Component.objects.filter(base_type=Switch.base_type),
        required=False, widget=autocomplete.ModelSelect2(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const([
                    Switch.base_type,
                ], 'base_type'),
            )
        )
    )
    mode = forms.ChoiceField(
        choices=(('heater', "Heater"), ('cooler', "Cooler"), ('auto', "Auto"),),
        initial='heater'
    )
    reaction_difference = forms.FloatField(initial=0.5)
    min = forms.IntegerField(initial=3)
    max = forms.IntegerField(initial=36)
    use_real_feel = forms.BooleanField(
        label=_("Use real feel as target temperature"), required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if dynamic_settings['core__units_of_measure'] == 'imperial':
            self.fields['min'].initial = 36
            self.fields['max'].initial = 100
        if self.instance.pk:
            self.fields['mode'].initial = \
                self.instance.config['user_config']['mode']
            temperature_sensor = Component.objects.filter(
                pk=self.instance.config.get('temperature_sensor', 0)
            ).first()
            if temperature_sensor \
            and temperature_sensor.base_type == MultiSensor.base_type:
                self.fields['use_real_feel'].initial = self.instance.config[
                    'user_config'
                ].get('use_real_feel')
            else:
                self.fields['use_real_feel'].disabled = True



    def save(self, commit=True):
        self.instance.value_units = self.cleaned_data[
            'temperature_sensor'
        ].value_units
        if not self.instance.config.get('user_config'):
            from .controllers import Thermostat
            self.instance.config['user_config'] = config_to_dict(
                Thermostat(self.instance)._get_default_user_config()
            )
        self.instance.config['user_config']['mode'] = self.cleaned_data['mode']
        self.instance.config['has_real_feel'] = True if self.cleaned_data[
            'temperature_sensor'
        ].base_type == MultiSensor.base_type else False
        self.instance.config['user_config']['use_real_feel'] = \
        self.cleaned_data['use_real_feel']
        return super().save(commit)


# TODO: create control widget for admin use.
class AlarmGroupConfigForm(BaseComponentForm):
    components = forms.ModelMultipleChoiceField(
        Component.objects.filter(
            Q(alarm_category__isnull=False) | Q(base_type='alarm-group')
        ),
        required=True,
        widget=autocomplete.ModelSelect2Multiple(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const(['security', 'fire', 'flood', 'other'], 'alarm_category'),
            )
        )
    )
    is_main = forms.BooleanField(
        required=False,
        help_text="Defines if this is your main/top global alarm group."
    )
    has_alarm = False


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .controllers import AlarmGroup
        if not self.instance.pk:
            first_alarm_group = bool(
                not Component.objects.filter(
                    controller_uid=AlarmGroup.uid,
                    config__is_main=True
                ).count()
            )
            self.fields['is_main'].initial = first_alarm_group
            if first_alarm_group:
                self.fields['is_main'].widget.attrs['disabled'] = 'disabled'
        else:
            if self.instance.config.get('is_main'):
                self.fields['is_main'].widget.attrs['disabled'] = 'disabled'


    def recurse_check_alarm_groups(self, components, start_comp=None):
        for comp in components:
            check_cmp = start_comp if start_comp else comp
            if comp.pk == self.instance.pk:
                raise forms.ValidationError(
                    "Can not cover self. Please remove - [%s]" % str(check_cmp)
                )
            if comp.base_type == 'alarm-group':
                self.recurse_check_alarm_groups(
                    comp.get_children(), check_cmp
                )

    def clean_components(self):
        self.recurse_check_alarm_groups(self.cleaned_data['components'])
        return self.cleaned_data['components']


    def save(self, *args, **kwargs):
        self.instance.value_units = 'status'
        from .controllers import AlarmGroup
        if self.fields['is_main'].widget.attrs.get('disabled'):
            self.cleaned_data['is_main'] = self.fields['is_main'].initial
        obj = super().save(*args, **kwargs)
        if obj.config.get('is_main'):
            for c in Component.objects.filter(
                controller_uid=AlarmGroup.uid,
                config__is_main=True
            ).exclude(pk=obj.pk):
                c.config['is_main'] = False
                c.save(update_fields=('config',))
        if obj.id:
            comp = Component.objects.get(id=obj.id)
            comp.refresh_status()
        return obj


class IPCameraConfigForm(BaseComponentForm):
    rtsp_address = forms.CharField(
        required=True,
        help_text="Use lower resolution stream. Include user credentials if needed. <br><br>"
                  "HKVISION Example: rtsp://admin:Passw0rd!@192.168.1.210:554/Streaming/Channels/2",
        widget=forms.TextInput(attrs={'style': 'width: 500px'})

    )

class WeatherForecastForm(BaseComponentForm):
    is_main = forms.BooleanField(
        required=False,
        help_text="Defines if this is your main/top global weather forecast."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .controllers import WeatherForecast
        if not self.instance.pk:
            first_weather_forecast = bool(
                not Component.objects.filter(
                    controller_uid=WeatherForecast.uid,
                    config__is_main=True
                ).count()
            )
            self.fields['is_main'].initial = first_weather_forecast
            if first_weather_forecast:
                self.fields['is_main'].widget.attrs['disabled'] = 'disabled'
        else:
            if self.instance.config.get('is_main'):
                self.fields['is_main'].widget.attrs['disabled'] = 'disabled'


    def save(self, *args, **kwargs):
        self.instance.value_units = 'status'
        from .controllers import WeatherForecast
        if self.fields['is_main'].widget.attrs.get('disabled'):
            self.cleaned_data['is_main'] = self.fields['is_main'].initial
        obj = super().save(*args, **kwargs)
        if obj.config.get('is_main'):
            for c in Component.objects.filter(
                controller_uid=WeatherForecast.uid,
                config__is_main=True
            ).exclude(pk=obj.pk):
                c.config['is_main'] = False
                c.save(update_fields=('config',))
        return obj


class GateConfigForm(BaseComponentForm):
    open_closed_sensor = forms.ModelChoiceField(
        Component.objects.filter(base_type=BinarySensor.base_type),
        label="Open/Closed sensor",
        widget=autocomplete.ModelSelect2(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const([BinarySensor.base_type], 'base_type'),
            )
        )
    )
    action_switch = forms.ModelChoiceField(
        Component.objects.filter(base_type=Switch.base_type),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const([Switch.base_type], 'base_type'),
            )
        )
    )
    action_method = forms.ChoiceField(
        required=True, choices=(
            ('click', "Click"),
            ('toggle', "Toggle"),
        ),
        help_text="Action switch method to initiate move/stop event on "
                  "your gate."
    )
    gate_open_duration = forms.FloatField(
        label='Gate open duration', min_value=0.01, max_value=360000,
        initial=30,
        help_text="Time in seconds it takes for your gate to go "
                  "from fully closed to fully open."
    )


class BlindsConfigForm(BaseComponentForm):
    open_switch = forms.ModelChoiceField(
        Component.objects.filter(base_type=Switch.base_type),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const([Switch.base_type], 'base_type'),
            )
        )
    )
    close_switch = forms.ModelChoiceField(
        Component.objects.filter(base_type=Switch.base_type),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const([Switch.base_type], 'base_type'),
            )
        )
    )
    open_direction = forms.ChoiceField(
        label='Closed > Open direction',
        required=True, choices=(
            ('up', "Up"), ('down', "Down"),
            ('right', "Right"), ('left', "Left")
        ),
        help_text="Move direction from fully closed to fully open."

    )
    open_duration = forms.FloatField(
        label='Open duration', min_value=0.001, max_value=360000,
        initial=30,
        help_text="Time in seconds it takes for your blinds to go "
                  "from fully closed to fully open."
    )
    slats_angle_duration = forms.FloatField(
        label='Slats angle duration', min_value=0.01, max_value=360000,
        required=False,
        help_text="Takes effect only with App control mode - 'Slide', "
                  "can be used with slat blinds to control slats angle. <br>"
                  "Time in seconds it takes "
                  "to go from fully closed to the start of open movement. <br>"
                  "Usually it's in between of 1 - 3 seconds."
    )
    control_mode = forms.ChoiceField(
        label="App control mode", required=True, choices=(
            ('click', "Click"), ('hold', "Hold"), ('slide', "Slide")
        ),
    )


class ContourForm(forms.Form):
    uid = forms.CharField(widget=forms.HiddenInput(), required=False)
    color = forms.CharField(widget=forms.HiddenInput(), required=False)

    name = forms.CharField()
    switch = forms.ModelChoiceField(
        Component.objects.filter(base_type=Switch.base_type),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const([Switch.base_type], 'base_type'),
            )
        ),
    )
    runtime = forms.IntegerField(
        min_value=0,
        help_text="Contour runtime in minutes. "
                  "Users can adjust this later in the app."
    )
    occupation = forms.IntegerField(
        min_value=1, max_value=100, initial=100,
        help_text="How much in % of total water stream does this contour "
                  "occupies when opened."
    )

    prefix = 'contours'


class WateringConfigForm(BaseComponentForm):
    COLORS = [
        "#00E1FF", "#FF00FF", "#9A00FF", "#45FFD6", "#D1FF00",
        "#0000FF", "#FF0000", "#00E1FF", "#E0AAFF", "#00E139",
        "#E0E1FF", "#921D3E", "#F15A29", "#FBB040", "#F9ED32",
        "#8DC63F", "#006838", "#1C75BC", "#9E1F63", "#662D91"
    ]
    contours = FormsetField(
        formset_factory(ContourForm, can_delete=True, can_order=True, extra=0)
    )
    ai_assist = forms.BooleanField(
        label="Enabled/disabled AI assist",
        required=False, initial=True,
        help_text="Save water by skipping scheduled watering events based "
                  "on previous, current and predicted weather in your area."
    )
    # https://www.boughton.co.uk/products/topsoils/soil-types/
    soil_type = forms.ChoiceField(
        choices=(
            ('loamy', 'Loamy'),
            ('silty', "Silty Soil"),
            ('sandy', "Sandy Soil"),
            ('clay', "Clay Soil"),
            ('peaty', "Peaty Soil"),
            ('chalky', "Chalky Soil"),
        )
    )
    ai_assist_level = forms.IntegerField(
        min_value=0, max_value=100, initial=50,
        help_text="0 - do not skip watering, unless it was cold and raining for weeks. <br>"
                  "100 - try to save as much water as possible by avoiding "
                  "watering program as much as possible. "
    )

    def clean_contours(self):
        contours = self.cleaned_data['contours']
        names = set()
        for i, cont in enumerate(contours):
            if cont['name'] in names:
                raise forms.ValidationError('Contour names must be unique!')
            names.add(cont['name'])
            if not cont['color']:
                cont['color'] = self.COLORS[i % len(self.COLORS)]
            if not cont['uid']:
                cont['uid'] = get_random_string(6)
        return contours

    def save(self, commit=True):
        self.instance.config['program'] = self.controller._build_program(
            self.cleaned_data['contours']
        )
        obj = super().save(commit=commit)
        if commit:
            obj.subcomponents.clear()
            for contour in self.cleaned_data['contours']:
                obj.subcomponents.add(
                    Component.objects.get(pk=contour['switch'])
                )
        return obj


class StateForm(forms.Form):
    icon = AutocompleteSelect2(url='autocomplete-icon')
    slug = forms.SlugField(required=True)
    name = forms.CharField(required=True)
    help_text = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))
    prefix = 'states'


class StateSelectForm(BaseComponentForm):
    states = FormsetField(
        formset_factory(StateForm, can_delete=True, can_order=True, extra=0)
    )


ACTION_METHODS = (
    ('turn_on', "Turn ON"), ('turn_off', "Turn OFF"),
    ('play', "Play"), ('pause', "Pause"), ('stop', "Stop"),
    ('open', 'Open'), ('close', 'Close'),
    ('lock', "Lock"), ('unlock', "Unlock"),
)


class AlarmClockEventForm(forms.Form):
    uid = forms.CharField(widget=forms.HiddenInput(), required=False)
    enabled = forms.BooleanField(initial=True)
    name = forms.CharField(max_length=30)
    component = forms.ModelChoiceField(
        Component.objects.all(),
        widget=autocomplete.ModelSelect2(
            url='autocomplete-component', attrs={'data-html': True},
        ),
    )
    play_action = forms.ChoiceField(
        initial='turn_on', choices=ACTION_METHODS
    )
    reverse_action = forms.ChoiceField(
        required=False, initial='turn_off', choices=ACTION_METHODS
    )
    offset = forms.IntegerField(min_value=-120, max_value=120, initial=0)

    prefix = 'default_events'

    def clean(self):
        if not self.cleaned_data.get('component'):
            return self.cleaned_data
        if not self.cleaned_data.get('play_method'):
            return self.cleaned_data
        component = self.cleaned_data.get('component')
        if not hasattr(component, self.cleaned_data['play_method']):
            self.add_error(
                'play_method',
                f"{component} has no {self.cleaned_data['play_method']} method!"
            )
        if self.cleaned_data.get('reverse_method'):
            if not hasattr(component, self.cleaned_data['reverse_method']):
                self.add_error(
                    'reverse_method',
                    f"{component} has no "
                    f"{self.cleaned_data['reverse_method']} method!"
                )
        return self.cleaned_data


class AlarmClockConfigForm(BaseComponentForm):
    default_events = FormsetField(
        formset_factory(
            AlarmClockEventForm, can_delete=True, can_order=True, extra=0
        ), label='Default events'
    )

    def clean_default_events(self):
        events = self.cleaned_data['default_events']
        for i, cont in enumerate(events):
            if not cont['uid']:
                cont['uid'] = get_random_string(6)
        return events

    def save(self, commit=True):
        obj = super().save(commit=commit)
        if commit:
            obj.subcomponents.clear()
            for comp in self.cleaned_data['default_events']:
                obj.subcomponents.add(
                    Component.objects.get(pk=comp['component'])
                )
        return obj
