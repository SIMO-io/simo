import time
from django import forms
from django.utils.translation import gettext_lazy as _
from django.forms import formset_factory
from django.urls.base import get_script_prefix
from django.contrib.contenttypes.models import ContentType
from dal import autocomplete
from dal import forward
from simo.core.models import Component
from simo.core.forms import (
    BaseComponentForm, ValueLimitForm, NumericSensorForm, SwitchForm
)
from simo.core.utils.formsets import FormsetField
from simo.core.widgets import LogOutputWidget
from simo.core.utils.easing import EASING_CHOICES
from simo.core.utils.validators import validate_slaves
from simo.core.utils.admin import AdminFormActionForm
from simo.core.events import GatewayObjectCommand
from simo.core.form_fields import Select2ModelChoiceField, Select2ListChoiceField
from .models import Colonel, ColonelPin, Interface
from .utils import INTERFACES_PINS_MAP, get_all_control_input_choices


class ColonelPinChoiceField(forms.ModelChoiceField):
    '''
    Required for API, so that SIMO app could properly handle
    fleet components configuration.
    '''
    filter_by = 'colonel'


class ColonelInterfacesChoiceField(forms.ModelChoiceField):
    filter_by = 'colonel'



class ColonelAdminForm(forms.ModelForm):
    log = forms.CharField(
        widget=forms.HiddenInput, required=False
    )

    class Meta:
        model = Colonel
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            prefix = get_script_prefix()
            if prefix == '/':
                prefix = ''
            self.fields['log'].widget = LogOutputWidget(
                prefix + '/ws/log/%d/%d/' % (
                    ContentType.objects.get_for_model(Colonel).id,
                    self.instance.id
                )
            )


class MoveColonelForm(AdminFormActionForm):
    colonel = forms.ModelChoiceField(
        label="Move to:", queryset=Colonel.objects.filter(components=None),
    )


class InterfaceAdminForm(forms.ModelForm):

    class Meta:
        model = Interface
        fields = '__all__'

    def clean(self):
        if self.instance.pk:
            return self.cleaned_data

        for pin_no in INTERFACES_PINS_MAP[self.cleaned_data['no']]:
            cpin = ColonelPin.objects.get(
                colonel=self.instance.colonel, no=pin_no
            )
            if cpin.occupied_by:
                raise forms.ValidationError(
                    f"Interface can not be created, because "
                    f"GPIO{cpin} is already occupied by {cpin.occupied_by}."
                )


class ColonelComponentForm(BaseComponentForm):
    colonel = forms.ModelChoiceField(
        label="Colonel", queryset=Colonel.objects.all()
    )

    def clean_colonel(self):
        if not self.instance.pk:
            return self.cleaned_data['colonel']
        colonel = self.cleaned_data.get('colonel')
        if not colonel:
            return
        org = self.instance.config.get('colonel')
        if org and org != colonel.id:
            raise forms.ValidationError(
                "Changing colonel after component is created "
                "it is not allowed!"
            )
        return colonel

    def _clean_pin(self, field_name):
        if self.cleaned_data[field_name].colonel != self.cleaned_data['colonel']:
            self.add_error(
                field_name, "Pin must be from the same Colonel!"
            )
            return
        if self.cleaned_data[field_name].occupied_by \
        and self.cleaned_data[field_name].occupied_by != self.instance:
            self.add_error(
                field_name,
                f"Pin is already occupied by {self.cleaned_data[field_name].occupied_by}!"
            )

    def _clean_controls(self):
        # TODO: Formset factory should return proper field value types instead of str type

        pin_instances = {}
        for i, control in enumerate(self.cleaned_data['controls']):
            updated_vals = {}
            for key, val in control.items():
                updated_vals[key] = val
                if key == 'input':
                    if val.startswith('pin'):
                        pin = ColonelPin.objects.get(
                            id=int(self.cleaned_data['controls'][i]['input'][4:])
                        )
                        pin_instances[i] = pin
                        updated_vals['pin_no'] = pin.no
                    elif val.startswith('button'):
                        updated_vals['button'] = int(
                            self.cleaned_data['controls'][i]['input'][7:]
                        )
                elif key == 'touch_threshold':
                    updated_vals[key] = int(val)
            self.cleaned_data['controls'][i] = updated_vals

        pins_in_use = []
        formset_errors = {}
        for i, control in enumerate(self.cleaned_data['controls']):
            if not control['input'].startswith('pin'):
                continue
            if pin_instances[i].colonel != self.cleaned_data['colonel']:
                formset_errors[i] = {
                    'input': f"{pin_instances[i]} must be from the same Colonel!"
                }
            elif pin_instances[i].occupied_by \
            and pin_instances[i].occupied_by != self.instance:
                formset_errors[i] = {
                    'pin': f"{pin_instances[i]} is already occupied by {pin_instances[i].occupied_by}!"
                }
            elif pin_instances[i].no in pins_in_use:
                formset_errors[i] = {
                    'pin': f"{pin_instances[i].no} is already in use!"
                }
            pins_in_use.append(pin_instances[i].no)

        errors_list = []
        if formset_errors:
            for i, control in enumerate(self.cleaned_data['controls']):
                errors_list.append(formset_errors.get(i, {}))
        if errors_list:
            self._errors['controls'] = errors_list
            if 'controls' in self.cleaned_data:
                del self.cleaned_data['controls']


class ControlForm(forms.Form):
    input = Select2ListChoiceField(
        choices=get_all_control_input_choices,
        url='autocomplete-control_inputs', forward=[
            forward.Self(), forward.Field('colonel'),
            forward.Const({'input': True}, 'pin_filters')
        ]
    )
    method = forms.ChoiceField(
        label="Button type",
        required=True, choices=(
            ('momentary', "Momentary"), ('toggle', "Toggle"),
        ),
    )
    action_method = forms.ChoiceField(
        label="Action method (if Momentary)", initial='down',
        choices=(
            ('down', "DOWN (On GND delivery)"),
            ('up', "UP (On +5V delivery)")
        )
    )

    prefix = 'controls'


class ColonelBinarySensorConfigForm(ColonelComponentForm):
    pin = ColonelPinChoiceField(
        label='Port',
        queryset=ColonelPin.objects.filter(input=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'input': True}, 'filters')
            ]
        )
    )
    inverse = forms.TypedChoiceField(
        choices=((1, "Yes"), (0, "No")), coerce=int, initial=1,
        help_text="Hint: Set inverse to Yes, to get ON signal when "
                  "you deliver GND to the input and OFF when you cut it out."
    )
    debounce = forms.IntegerField(
        min_value=0, max_value=1000 * 60 * 60, required=False, initial=50,
        help_text="Some sensors are unstable and quickly transition "
                  "between ON/OFF states when engaged. <br>"
                  "Set debounce value in milliseconds, to remediate this. "
                  "50ms offers a good starting point!"
    )
    hold_time = forms.TypedChoiceField(
        initial=0, coerce=int, choices=(
            (0, "-----"),
            (1, "10 s"), (2, "20 s"), (3, "30 s"), (4, "40 s"), (5, "50 s"),
            (6, "1 min"), (9, "1.5 min"), (12, "2 min"), (18, "3 min"),
            (30, "5 min"), (60, "10 min"), (120, "20 min"),
        ), required=False,
        help_text="Holds positive value for given amount of time "
                  "after last negative value has been observed. "
                  "Super useful with regular motion detectors for controlling "
                  "lights or other means of automation."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.basic_fields.append('hold_time')

    def clean(self):
        super().clean()
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data

        self._clean_pin('pin')

        if self.cleaned_data['pin'].no > 100:
            if self.cleaned_data['pin'].no < 126:
                if self.cleaned_data.get('pull') == 'HIGH':
                    self.add_error(
                        'pull',
                        "Sorry, but this pin is already pulled LOW and "
                        "it can not be changed by this setting. "
                        "Please use 5kohm resistor to physically pull it HIGH "
                        "if that's what you want to do."
                    )
            else:
                if self.cleaned_data.get('pull') == 'LOW':
                    self.add_error(
                        'pull',
                        "Sorry, but this pin is already pulled HIGH and "
                        "it can not be changed by this setting. "
                        "Please use 5kohm resistor to physically pull it LOW "
                        "if that's what you want to do."
                    )

        elif self.cleaned_data.get('pull') != 'FLOATING':
            if not self.cleaned_data['pin'].output:
                self.add_error(
                    'pin',
                    f"Sorry, but {self.cleaned_data['pin']} "
                    f"does not have internal pull HIGH/LOW"
                    " resistance capability"
                )

        return self.cleaned_data

    def save(self, commit=True):
        if 'pin' in self.cleaned_data:
            self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)


class ColonelButtonConfigForm(ColonelComponentForm):
    pin = ColonelPinChoiceField(
        label="Port",
        queryset=ColonelPin.objects.filter(input=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'input': True}, 'filters')
            ]
        )
    )
    action_method = forms.ChoiceField(
        label="Action method", initial='down',
        choices=(
            ('down', "DOWN (On GND delivery)"),
            ('up', "UP (On +5V delivery)")
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data
        self._clean_pin('pin')
        return self.cleaned_data

    def save(self, commit=True):
        if 'pin' in self.cleaned_data:
            self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)


class ColonelNumericSensorConfigForm(ColonelComponentForm, NumericSensorForm):
    pin = ColonelPinChoiceField(
        label="Port",
        queryset=ColonelPin.objects.filter(adc=True, input=True, native=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const(
                    {'adc': True, 'native': True, 'input': True}, 'filters'
                )
            ]
        )
    )
    attenuation = forms.TypedChoiceField(
        initial=0, coerce=int, choices=(
            (0, "Max 1v"), (2, "Max 1.34v"), (6, "Max 2v"), (11, "Max 3.6v")
        )
    )
    read_frequency_s = forms.FloatField(
        initial=60, min_value=1, max_value=60*60*24,
        help_text='read input value every s'
    )
    change_report = forms.FloatField(
        initial=0.2,
        help_text='consider value as changed if it changes this much'
    )

    limits = FormsetField(
        formset_factory(
            ValueLimitForm, can_delete=True, can_order=True, extra=0, max_num=3
        )
    )

    def clean(self):
        super().clean()
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data

        self._clean_pin('pin')

        return self.cleaned_data


    def save(self, commit=True):
        if 'pin' in self.cleaned_data:
            self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)


class DS18B20SensorConfigForm(ColonelComponentForm, NumericSensorForm):
    pin = ColonelPinChoiceField(
        label="Port",
        queryset=ColonelPin.objects.filter(input=True, native=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const(
                    {'native': True, 'input': True}, 'filters'
                )
            ]
        )
    )
    read_frequency_s = forms.IntegerField(
        initial=60, min_value=1, max_value=60*60*24,
        help_text='read and  report temperature value every s. '
                              'Can not be less than 1s.'
    )


    def clean(self):
        super().clean()
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data

        self._clean_pin('pin')

        return self.cleaned_data

    def save(self, commit=True):
        if 'pin' in self.cleaned_data:
            self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)



class ColonelDHTSensorConfigForm(ColonelComponentForm):
    pin = ColonelPinChoiceField(
        label="Port",
        queryset=ColonelPin.objects.filter(input=True, native=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const(
                    {'native': True, 'input': True}, 'filters'
                )
            ]
        )
    )
    sensor_type = forms.TypedChoiceField(
        initial=11, coerce=int, choices=(
            (11, "DHT11"), (22, "DHT22"),
        )
    )
    temperature_units = forms.ChoiceField(
        label="Sensor temperature units",
        choices=(('C', "Celsius"), ('F', "Fahrenheit"))
    )
    read_frequency_s = forms.IntegerField(
        initial=60, min_value=1, max_value=60*60*24,
        help_text='read and  report climate value every s. '
                              'Can not be less than 1s.'
    )

    def clean(self):
        super().clean()
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data

        self._clean_pin('pin')

        return self.cleaned_data

    def save(self, commit=True):
        if 'pin' in self.cleaned_data:
            self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)


class BME680SensorConfigForm(ColonelComponentForm):
    interface = ColonelInterfacesChoiceField(
        queryset=Interface.objects.filter(type='i2c'),
        widget=autocomplete.ListSelect2(
            url='autocomplete-interfaces',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const(
                    {'type': 'i2c'}, 'filters'
                )
            ]
        )
    )
    i2c_address = forms.TypedChoiceField(
        coerce=int, initial=118,
        choices=((118, "0x76"), (119, "0x77")),
    )
    read_frequency_s = forms.IntegerField(
        initial=60, min_value=1, max_value=60*60*24,
        help_text='read and report climate value every s. '
                              'Can not be less than 1s.'

    )

    def clean(self):
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if self.cleaned_data['interface'].colonel != self.cleaned_data['colonel']:
            self.add_error(
                'interface',
                f"This interface is on {self.cleaned_data['interface'].colonel}, "
                f"however we need an interface from {self.cleaned_data['colonel']}."
            )
        other_comp = Component.objects.filter(
            config__colonel=self.cleaned_data['colonel'].id,
            config__interface=self.cleaned_data['interface'].id,
            config__i2c_address=self.cleaned_data['i2c_address']
        ).exclude(id=self.instance.id).first()
        if other_comp:
            self.add_error('i2c_address', f'Already occupied by {other_comp}!')
        return self.cleaned_data

    def save(self, commit=True):
        if 'interface' in self.cleaned_data:
            self.instance.config['i2c_interface'] = self.cleaned_data['interface'].no
        return super().save(commit=commit)


class MPC9808SensorConfigForm(ColonelComponentForm):
    interface = ColonelInterfacesChoiceField(
        queryset=Interface.objects.filter(type='i2c'),
        widget=autocomplete.ListSelect2(
            url='autocomplete-interfaces',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const(
                    {'type': 'i2c'}, 'filters'
                )
            ]
        )
    )
    i2c_address = forms.TypedChoiceField(
        coerce=int, initial=24,
        choices=(
            (24, "Default"),
            (25, "AD0"), (26, "AD1"), (28, "AD2"),
            (27, "AD0 + AD1"), (29, "AD0 + AD2"), (30, "AD1 + AD2"),
            (31, "AD0 + AD1 + AD2")
        ),
    )
    read_frequency_s = forms.IntegerField(
        initial=60, min_value=1, max_value=60 * 60 * 24,
        help_text='read and report temperature value every s. '
                  'Can not be less than 1s.'

    )

    def clean(self):
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if self.cleaned_data['interface'].colonel != self.cleaned_data['colonel']:
            self.add_error(
                'interface',
                f"This interface is on {self.cleaned_data['interface'].colonel}, "
                f"however we need an interface from {self.cleaned_data['colonel']}."
            )

        other_comp = Component.objects.filter(
            config__colonel=self.cleaned_data['colonel'].id,
            config__interface=self.cleaned_data['interface'].id,
            config__i2c_address=self.cleaned_data['i2c_address']
        ).exclude(id=self.instance.id).first()
        if other_comp:
            self.add_error('i2c_address', f'Already occupied by {other_comp}!')
        return self.cleaned_data

    def save(self, commit=True):
        if 'interface' in self.cleaned_data:
            self.instance.config['i2c_interface'] = self.cleaned_data['interface'].no
        return super().save(commit=commit)


class ENS160SensorConfigForm(ColonelComponentForm):
    interface = ColonelInterfacesChoiceField(
        queryset=Interface.objects.filter(type='i2c'),
        widget=autocomplete.ListSelect2(
            url='autocomplete-interfaces',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const(
                    {'type': 'i2c'}, 'filters'
                )
            ]
        )
    )
    i2c_address = forms.TypedChoiceField(
        coerce=int, initial=83,
        choices=((82, "0x52"), (83, "0x53")),
    )
    read_frequency_s = forms.IntegerField(
        initial=10, min_value=1, max_value=60 * 60 * 24,
        help_text='read and report air quality values every s. '
                  'Can not be less than 1s.'

    )

    def clean(self):
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if self.cleaned_data['interface'].colonel != self.cleaned_data['colonel']:
            self.add_error(
                'interface',
                f"This interface is on {self.cleaned_data['interface'].colonel}, "
                f"however we need an interface from {self.cleaned_data['colonel']}."
            )
        other_comp = Component.objects.filter(
            config__colonel=self.cleaned_data['colonel'].id,
            config__interface=self.cleaned_data['interface'].id,
            config__i2c_address=self.cleaned_data['i2c_address']
        ).exclude(id=self.instance.id).first()
        if other_comp:
            self.add_error('i2c_address', f'Already occupied by {other_comp}!')
        return self.cleaned_data

    def save(self, commit=True):
        if 'interface' in self.cleaned_data:
            self.instance.config['i2c_interface'] = \
                self.cleaned_data['interface'].no
        return super().save(commit=commit)


class ColonelTouchSensorConfigForm(ColonelComponentForm):
    pin = ColonelPinChoiceField(
        label="Port",
        queryset=ColonelPin.objects.filter(input=True, capacitive=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'input': True, 'capacitive': True}, 'filters')
            ]
        )
    )
    threshold = forms.IntegerField(
        min_value=0, max_value=999999999, required=False, initial=1000,
        help_text="Used to detect touch events. "
                  "Smaller value means a higher sensitivity. "
                  "1000 offers good starting point."

    )
    inverse = forms.ChoiceField(choices=((0, "No"), (1, "Yes")))

    def clean(self):
        super().clean()
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data

        self._clean_pin('pin')

        return self.cleaned_data


    def save(self, commit=True):
        if 'pin' in self.cleaned_data:
            self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)


class ColonelSwitchConfigForm(ColonelComponentForm):
    output_pin = Select2ModelChoiceField(
        label="Port",
        queryset=ColonelPin.objects.filter(output=True),
        url='autocomplete-colonel-pins',
        forward=[
            forward.Self(),
            forward.Field('colonel'),
            forward.Const({'output': True}, 'filters')
        ]
    )
    auto_off = forms.FloatField(
        required=False, min_value=0.01, max_value=1000000000,
        help_text="If provided, switch will be turned off after "
                  "given amount of seconds after every turn on event."
    )
    inverse = forms.BooleanField(required=False)
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

    controls = FormsetField(
        formset_factory(
            ControlForm, can_delete=True, can_order=True, extra=0, max_num=10
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.basic_fields.append('auto_off')
        if self.instance.pk and 'slaves' in self.fields:
            self.fields['slaves'].initial = self.instance.slaves.all()

    def clean_slaves(self):
        if 'slaves' not in self.cleaned_data:
            return
        if not self.cleaned_data['slaves'] or not self.instance:
            return self.cleaned_data['slaves']
        return validate_slaves(self.cleaned_data['slaves'], self.instance)

    def clean(self):
        super().clean()

        if self.cleaned_data.get('output_pin'):
            self._clean_pin('output_pin')
        if self.cleaned_data.get('controls'):
            self._clean_controls()

        if self.cleaned_data.get('output_pin') and self.cleaned_data.get('controls'):
            for ctrl in self.cleaned_data['controls']:
                if not ctrl['input'].startswith('pin'):
                    continue
                if int(ctrl['input'][4:]) == self.cleaned_data['output_pin'].id:
                    self.add_error(
                        "output_pin",
                        "Can't be used as control pin at the same time!"
                    )

        return self.cleaned_data

    def save(self, commit=True):
        if 'output_pin' in self.cleaned_data:
            self.instance.config['output_pin_no'] = self.cleaned_data['output_pin'].no
        obj = super().save(commit=commit)
        if commit and 'slaves' in self.cleaned_data:
            obj.slaves.set(self.cleaned_data['slaves'])
        if commit and self.cleaned_data.get('controls'):
            GatewayObjectCommand(
                self.instance.gateway, obj, command='watch_buttons'
            ).publish()
        return obj


class ColonelPWMOutputConfigForm(ColonelComponentForm):
    output_pin = ColonelPinChoiceField(
        label="Port",
        queryset=ColonelPin.objects.filter(output=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'output': True}, 'filters')
            ]
        )
    )
    min = forms.FloatField(
        required=True, initial=0,
        help_text="Minimum component value"
    )
    max = forms.FloatField(
        required=True, initial=100,
        help_text="Maximum component value"
    )
    value_units = forms.CharField(required=False)
    duty_min = forms.IntegerField(
        min_value=0, max_value=1023, required=True, initial=0,
        help_text="Minumum PWM signal output duty (0 - 1023)"
    )
    duty_max = forms.IntegerField(
        min_value=0, max_value=1023, required=True, initial=900,
        help_text="Maximum PWM signal output duty (0 - 1023)"
    )
    turn_on_time = forms.IntegerField(
        min_value=0, max_value=60000, initial=1000,
        help_text="Turn on speed in ms. 1500 is a great quick default. "
                  "10000 - great slow default."
    )
    turn_off_time = forms.IntegerField(
        min_value=0, max_value=60000, initial=20000,
        help_text="Turn off speed in ms. 3000 is a great quick default. "
                  "20000 - great slow default"
    )
    skew = forms.ChoiceField(
        initial='easeOutSine', choices=EASING_CHOICES,
        help_text="easeOutSine - offers most naturally looking effect."
    )
    inverse = forms.BooleanField(
        label=_("Inverse dimmer signal"), required=False, initial=True
    )
    on_value = forms.FloatField(
        required=True, initial=100,
        help_text="ON value when used with toggle switch"
    )

    slaves = forms.ModelMultipleChoiceField(
        required=False,
        queryset=Component.objects.filter(
            base_type__in=('dimmer', ),
        ),
        widget=autocomplete.ModelSelect2Multiple(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(forward.Const(['dimmer', ], 'base_type'),)
        )
    )
    controls = FormsetField(
        formset_factory(
            ControlForm, can_delete=True, can_order=True, extra=0, max_num=10
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'value_units' in self.fields:
            self.fields['value_units'].initial = self.controller.default_value_units
        self.basic_fields.extend(
            ['value_units', 'turn_on_time', 'turn_off_time', 'skew']
        )
        if self.instance.pk and 'slaves' in self.fields:
            self.fields['slaves'].initial = self.instance.slaves.all()

    def clean_slaves(self):
        if not self.cleaned_data['slaves'] or not self.instance:
            return self.cleaned_data['slaves']
        return validate_slaves(self.cleaned_data['slaves'], self.instance)

    def clean(self):
        super().clean()
        if 'output_pin' in self.cleaned_data:
            self._clean_pin('output_pin')
        if 'controls' in self.cleaned_data:
            self._clean_controls()

        if self.cleaned_data.get('output_pin') and self.cleaned_data.get('controls'):
            for ctrl in self.cleaned_data['controls']:
                if not ctrl['input'].startswith('pin'):
                    continue
                if int(ctrl['input'][4:]) == self.cleaned_data['output_pin'].id:
                    self.add_error(
                        "output_pin",
                        "Can't be used as control pin at the same time!"
                    )
        return self.cleaned_data


    def save(self, commit=True):
        if 'output_pin' in self.cleaned_data:
            self.instance.config['output_pin_no'] = self.cleaned_data['output_pin'].no

        update_colonel = False
        if not self.instance.pk:
            update_colonel = True
        elif 'output_pin' in self.changed_data:
            update_colonel = True
        elif 'slaves' in self.changed_data:
            update_colonel = True
        if not update_colonel:
            old = Component.objects.get(id=self.instance.id)
            if old.config.get('controls') != self.cleaned_data.get('controls'):
                update_colonel = True

        obj = super().save(commit=commit)
        if commit and 'slaves' in self.cleaned_data:
            obj.slaves.set(self.cleaned_data['slaves'])
        if not update_colonel:
            GatewayObjectCommand(
                obj.gateway, self.cleaned_data['colonel'], id=obj.id,
                command='call', method='update_config', args=[
                    obj.controller._get_colonel_config()
                ]
            ).publish()
        if commit and self.cleaned_data.get('controls'):
            GatewayObjectCommand(
                self.instance.gateway, obj, command='watch_buttons'
            ).publish()
        return obj


class ColonelRGBLightConfigForm(ColonelComponentForm):
    output_pin = ColonelPinChoiceField(
        label="Port",
        queryset=ColonelPin.objects.filter(output=True, native=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'output': True, 'native': True}, 'filters')
            ]
        )
    )
    num_leds = forms.IntegerField(
        label=_("Number of leds"), min_value=1, max_value=2000
    )
    strip_type = forms.ChoiceField(
        label="LED strip type",
        choices=(
            ("WS2811", "WS2811"),
            ('WS2812', "WS2812"),
            ('WS2812B', "WS2812B"),
            ('WS2813', "WS2813"),
            ('WS2815', "WS2815"),
            ('SK6812', "SK6812"),
            ('generic', "Generic"),
        )
    )
    has_white = forms.BooleanField(initial=False, required=False)
    color_order = forms.ChoiceField(
        required=False, choices=(
            (None, 'Default'),
            ("RGB", "RGB"), ("RBG", "RBG"), ("GRB", "GRB"),
            ("RGBW", "RGBW"), ("RBGW", "RBGW"), ("GRBW", "GRBW"),
        ),
    )
    custom_timing = forms.CharField(
        required=False,
        help_text="Custom addressable led strip timing (T0H, T0L, T1H, T1L). <br>"
                  "For example SK6812 is: (300, 900, 600, 600)"
    )
    sustain_color = forms.BooleanField(
        initial=True, required=False,
        help_text="Recommended to leave this enabled. <br>"
                  "Addressible signal wire might pick up electrical "
                  "noise from it's surroundings which might cause color change "
                  "on random pixels. Colonel will send color update every 20s "
                  "to sustain last set color if this is enabled. "
    )
    controls = FormsetField(
        formset_factory(
            ControlForm, can_delete=True, can_order=True, extra=0, max_num=2
        )
    )

    def save(self, commit=True):
        if 'output_pin' in self.cleaned_data:
            self.instance.config['output_pin_no'] = \
                self.cleaned_data['output_pin'].no
        obj = super().save(commit)
        if commit and self.cleaned_data.get('controls'):
            GatewayObjectCommand(
                self.instance.gateway, obj, command='watch_buttons'
            ).publish()
        return obj

    def clean_custom_timing(self):
        custom_timing = self.cleaned_data.get('custom_timing')
        if not custom_timing:
            return custom_timing
        custom_timing = custom_timing.strip().\
            strip('(').strip('[').rstrip(')').rstrip(']').split(',')
        if len(custom_timing) != 4:
            raise forms.ValidationError("Tuple of 4 integers please.")
        for t in custom_timing:
            try:
                t = int(t)
            except:
                raise forms.ValidationError(f"Integers only please.")
            if t <= 0:
                raise forms.ValidationError(f"Intervals must be greater than 0.")
            if t > 100000:
                raise forms.ValidationError(f"{t} seems way to much!")
        return f"({','.join(custom_timing)})"

    def clean(self):
        super().clean()

        if 'output_pin' in self.cleaned_data:
            self._clean_pin('output_pin')

        if self.cleaned_data.get('controls'):
            self._clean_controls()

        if self.cleaned_data.get('output_pin') and self.cleaned_data.get('controls'):
            for ctrl in self.cleaned_data['controls']:
                if not ctrl['input'].startswith('pin'):
                    continue
                if int(ctrl['input'][4:]) == self.cleaned_data['output_pin'].id:
                    self.add_error(
                        "output_pin",
                        "Can't be used as control pin at the same time!"
                    )

        if 'color_order' in self.cleaned_data:
            if self.cleaned_data.get('color_order'):
                if self.cleaned_data['has_white']:
                    if len(self.cleaned_data['color_order']) != 4:
                        self.add_error(
                            "color_order",
                            _("4 colors expected for stripes with dedicated White led.")
                        )
                else:
                    if len(self.cleaned_data['color_order']) != 3:
                        self.add_error(
                            "color_order",
                            _("3 colors expected for stripes without dedicated White led.")
                        )

        return self.cleaned_data



class DualMotorValveForm(ColonelComponentForm):
    open_pin = ColonelPinChoiceField(
        label="Open Relay Port",
        queryset=ColonelPin.objects.filter(output=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'output': True}, 'filters')
            ]
        )
    )
    open_action = forms.ChoiceField(
        choices=(('HIGH', "HIGH"), ('LOW', "LOW")),
    )
    open_duration = forms.FloatField(
        required=True, min_value=0.01, max_value=1000000000,
        initial=2, help_text="Time in seconds to open."
    )
    close_pin = ColonelPinChoiceField(
        label="Close Relay Port",
        queryset=ColonelPin.objects.filter(output=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'output': True}, 'filters')
            ]
        )
    )
    close_action = forms.ChoiceField(
        choices=(('HIGH', "HIGH"), ('LOW', "LOW")),
    )
    close_duration = forms.FloatField(
        required=True, min_value=0.01, max_value=1000000000,
        initial=10, help_text="Time in seconds to close."
    )


    def clean(self):
        super().clean()
        if self.cleaned_data.get('open_pin'):
            self._clean_pin('open_pin')
        if self.cleaned_data.get('close_pin'):
            self._clean_pin('close_pin')
        if self.cleaned_data.get('open_pin') \
        and self.cleaned_data.get('close_pin') \
        and self.cleaned_data['open_pin'] == self.cleaned_data['close_pin']:
            self.add_error(
                'close_pin', "Can't be the same as open pin!"
            )
        return self.cleaned_data

    def save(self, commit=True):
        if 'open_pin' in self.cleaned_data:
            self.instance.config['open_pin_no'] = \
                self.cleaned_data['open_pin'].no
        if 'close_pin' in self.cleaned_data:
            self.instance.config['close_pin_no'] = \
                self.cleaned_data['close_pin'].no
        obj = super().save(commit=commit)
        return obj


class BlindsConfigForm(ColonelComponentForm):
    open_pin = ColonelPinChoiceField(
        label="Open Relay Port",
        queryset=ColonelPin.objects.filter(output=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'output': True}, 'filters')
            ]
        )
    )
    open_action = forms.ChoiceField(
        choices=(('HIGH', "HIGH"), ('LOW', "LOW")),
    )
    close_pin = ColonelPinChoiceField(
        label="Close Relay Port",
        queryset=ColonelPin.objects.filter(output=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'output': True}, 'filters')
            ]
        )
    )
    close_action = forms.ChoiceField(
        choices=(('HIGH', "HIGH"), ('LOW', "LOW")),
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
        label='Open duration', min_value=1, max_value=360000,
        initial=30,
        help_text="Time in seconds it takes for your blinds to go "
                  "from fully closed to fully open."
    )
    close_duration = forms.FloatField(
        label='Close duration', min_value=1, max_value=360000,
        initial=30,
        help_text="Time in seconds it takes for your blinds to go "
                  "from fully open to fully closed."
    )
    control_type = forms.ChoiceField(
        initial=0, required=True, choices=(
            ('hold', "Hold"), ('click', 'Click')
        ),
        help_text="What type of blinds you have?<br>"
                  "Hold - blinds goes for as long as contacts are held together<br>"
                  "Click - blinds goes and stops with short click of ontroll contacts."
    )
    slats_angle_duration = forms.FloatField(
        label='Slats angle duration', min_value=0.1, max_value=360000,
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
    controls = FormsetField(
        formset_factory(
            ControlForm, can_delete=True, can_order=True, extra=0, max_num=2
        )
    )

    def clean(self):
        super().clean()

        if self.cleaned_data.get('open_pin') \
        and self.cleaned_data.get('close_pin') \
        and self.cleaned_data['open_pin'] == self.cleaned_data['close_pin']:
            self.add_error(
                'close_pin', "Can't be the same as open pin!"
            )

        if self.cleaned_data.get('open_pin'):
            self._clean_pin('open_pin')
        if self.cleaned_data.get('close_pin'):
            self._clean_pin('close_pin')

        if 'controls' in self.cleaned_data:
            if len(self.cleaned_data['controls']) not in (0, 1, 2):
                self.add_error('controls', "Must have 0, 1 or 2 controls")
                return self.cleaned_data

            if len(self.cleaned_data['controls']) == 2:
                method = None
                for c in self.cleaned_data['controls']:
                    if not method:
                        method = c['method']
                    else:
                        if c['method'] != method:
                            self.add_error('controls', "Both must use the same control method.")
                            return self.cleaned_data

            self._clean_controls()

            if self.cleaned_data.get('open_pin') and self.cleaned_data.get('controls'):
                for ctrl in self.cleaned_data['controls']:
                    if not ctrl['input'].startswith('pin'):
                        continue
                    if int(ctrl['input'][4:]) == self.cleaned_data['open_pin'].id:
                        self.add_error(
                            "open_pin",
                            "Can't be used as control pin at the same time!"
                        )

            if self.cleaned_data.get('close_pin') and self.cleaned_data.get('controls'):
                for ctrl in self.cleaned_data['controls']:
                    if not ctrl['input'].startswith('pin'):
                        continue
                    if int(ctrl['input'][4:]) == self.cleaned_data['close_pin'].id:
                        self.add_error(
                            "close_pin",
                            "Can't be used as control pin at the same time!"
                        )
        return self.cleaned_data

    def save(self, commit=True):
        if 'open_pin' in self.cleaned_data:
            self.instance.config['open_pin_no'] = \
                self.cleaned_data['open_pin'].no
        if 'close_pin' in self.cleaned_data:
            self.instance.config['close_pin_no'] = \
                self.cleaned_data['close_pin'].no
        obj = super().save(commit=commit)
        if commit and self.cleaned_data.get('controls'):
            GatewayObjectCommand(
                self.instance.gateway, obj, command='watch_buttons'
            ).publish()
        return obj


class BurglarSmokeDetectorConfigForm(ColonelComponentForm):
    power_pin = ColonelPinChoiceField(
        label="Power port",
        queryset=ColonelPin.objects.filter(output=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'output': True}, 'filters')
            ]
        )
    )
    sensor_pin = ColonelPinChoiceField(
        label="Sensor port",
        queryset=ColonelPin.objects.filter(input=True),
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'input': True}, 'filters')
            ]
        )
    )
    sensor_inverse = forms.TypedChoiceField(
        choices=((0, "No"), (1, "Yes")), coerce=int, initial=0,
        help_text="Hint: Set to Yes, to get ON signal when "
                  "you deliver GND to the pin and OFF when you cut it out."
    )

    def clean(self):
        super().clean()
        if 'sensor_pin' in self.cleaned_data:
            self._clean_pin('sensor_pin')
        if 'power_pin' in self.cleaned_data:
            self._clean_pin('power_pin')

        if self.cleaned_data.get('sensor_pin') \
        and self.cleaned_data.get('power_pin') \
        and self.cleaned_data['sensor_pin'] == self.cleaned_data['power_pin']:
            self.add_error(
                'power_pin', "Can't be the same as sensor pin!"
            )

        return self.cleaned_data

    def save(self, commit=True):
        if 'sensor_pin' in self.cleaned_data:
            self.instance.config['sensor_pin_no'] = \
                self.cleaned_data['sensor_pin'].no
        if 'power_pin' in self.cleaned_data:
            self.instance.config['power_pin_no'] = \
                self.cleaned_data['power_pin'].no
        return super().save(commit=commit)


class TTLockConfigForm(ColonelComponentForm):

    door_sensor = forms.ModelChoiceField(
        Component.objects.filter(base_type='binary-sensor'),
        required=False,
        help_text="Quickens up lock status reporting on open/close if provided.",
        widget=autocomplete.ModelSelect2(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const(['binary-sensor'], 'base_type'),
            )
        )
    )

    def clean(self):
        if not self.instance or not self.instance.pk:
            from .controllers import TTLock
            other_lock = self.cleaned_data['colonel'].components.filter(
                controller_uid=TTLock.uid
            ).first()
            if other_lock:
                raise forms.ValidationError(
                    f"Single Colonel can support single TTLock only.\n"
                    f"You already have {other_lock} on this Colonel."
                )
        return self.cleaned_data

    def save(self, commit=True):
        obj = super(ColonelComponentForm, self).save(commit)
        if commit and 'door_sensor' in self.cleaned_data:
            GatewayObjectCommand(
                self.instance.gateway, self.cleaned_data['door_sensor'],
                command='watch_lock_sensor'
            ).publish()
        return obj


class DALIDeviceConfigForm(ColonelComponentForm):
    interface = ColonelInterfacesChoiceField(
        queryset=Interface.objects.filter(type='dali'),
        widget=autocomplete.ListSelect2(
            url='autocomplete-interfaces',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const(
                    {'type': 'dali'}, 'filters'
                )
            ]
        )
    )

    def clean_interface(self):
        if not self.instance.pk:
            return self.cleaned_data['interface']
        if 'interface' in self.changed_data:
            raise forms.ValidationError(
                "Changing interface after component is created "
                "it is not allowed!"
            )
        return self.cleaned_data['interface']

    def clean(self):
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if self.cleaned_data['interface'].colonel != self.cleaned_data['colonel']:
            self.add_error(
                'interface',
                f"This interface is on {self.cleaned_data['interface'].colonel}, "
                f"however we need an interface from {self.cleaned_data['colonel']}."
            )
        return self.cleaned_data

    def save(self, commit=True):
        if 'interface' in self.cleaned_data:
            self.instance.config['dali_interface'] = \
                self.cleaned_data['interface'].no
        is_new = not self.instance.pk
        obj = super().save(commit=commit)
        if commit:
            if not is_new:
                GatewayObjectCommand(
                    obj.gateway, self.cleaned_data['colonel'], id=obj.id,
                    command='call', method='update_config', args=[
                        obj.controller._get_colonel_config()
                    ]
                ).publish()
        return obj


class DaliLampForm(DALIDeviceConfigForm, BaseComponentForm):
    fade_time = forms.TypedChoiceField(
        initial=1, coerce=int, choices=(
            (0, "Instant"),
            (1, "0.7 s"), (2, "1.0 s"), (3, "1.4 s"), (4, "2.0 s"), (5, "2.8 s"),
            (6, "4.0 s"), (7, "5.7 s"), (8, "8.0 s")
        )
    )
    gear_min = forms.IntegerField(
        min_value=1, max_value=254, initial=90,
        help_text="Minimum level at which device starts operating up (1 - 254), "
                  "SIMO.io DALI interface detects this value automatically when "
                  "pairing a new device. <br>"
                  "Most LED drivers we tested starts at 86. <br>"
                  "If you set this value to low, you might start seeing device "
                  "beings dying out when you hit it with lower value than it "
                  "is capable of supplying."
    )
    on_value = forms.FloatField(
        required=True, initial=100,
        help_text="ON value when used with toggle switch"
    )
    auto_off = forms.FloatField(
        required=False, min_value=0.01, max_value=1000000000,
        help_text="If provided, lamp will be turned off after "
                  "given amount of seconds after last turn on event."
    )
    controls = FormsetField(
        formset_factory(
            ControlForm, can_delete=True, can_order=True, extra=0, max_num=999
        )
    )

    def clean(self):
        if 'controls' in self.cleaned_data:
            self._clean_controls()
        return self.cleaned_data

    def save(self, commit=True):
        obj = super().save(commit=commit)
        if commit:
            if self.cleaned_data.get('controls'):
                GatewayObjectCommand(
                    self.instance.gateway, obj, command='watch_buttons'
                ).publish()
            if self.instance.pk:
                old_controls = Component.objects.get(
                    pk=self.instance.pk
                ).config.get('controls')
                if old_controls != self.cleaned_data.get('controls'):
                    self.cleaned_data['colonel'].update_config()
        return obj


class DaliSwitchConfigForm(DALIDeviceConfigForm, BaseComponentForm):
    auto_off = forms.FloatField(
        required=False, min_value=0.01, max_value=1000000000,
        help_text="If provided, lamp will be turned off after "
                  "given amount of seconds after last turn on event."
    )
    controls = FormsetField(
        formset_factory(
            ControlForm, can_delete=True, can_order=True, extra=0, max_num=999
        )
    )

    def clean(self):
        if 'controls' in self.cleaned_data:
            self._clean_controls()
        return self.cleaned_data

    def save(self, commit=True):
        obj = super().save(commit=commit)
        if commit:
            if self.cleaned_data.get('controls'):
                GatewayObjectCommand(
                    self.instance.gateway, obj, command='watch_buttons'
                ).publish()
            if self.instance.pk:
                old_controls = Component.objects.get(
                    pk=self.instance.pk
                ).config.get('controls')
                if old_controls != self.cleaned_data.get('controls'):
                    self.cleaned_data['colonel'].update_config()
        return obj


class DaliGearGroupForm(DALIDeviceConfigForm, BaseComponentForm):
    auto_off = forms.FloatField(
        required=False, min_value=0.01, max_value=1000000000,
        help_text="If provided, group will be turned off after "
                  "given amount of seconds after last turn on event."
    )
    members = forms.ModelMultipleChoiceField(
        Component.objects.filter(
            controller_uid='simo.fleet.controllers.DALILamp',
        ),
        label="Members", required=True,
        widget=autocomplete.ModelSelect2Multiple(
            url='autocomplete-component', attrs={'data-html': True},
            forward=(
                forward.Const(
                    ['simo.fleet.controllers.DALILamp', ], 'controller_uid'
                ),
            )
        )
    )
    on_value = forms.FloatField(
        required=True, initial=100,
        help_text="ON value when used with toggle switch"
    )
    controls = FormsetField(
        formset_factory(
            ControlForm, can_delete=True, can_order=True, extra=0, max_num=999
        )
    )

    def clean(self):
        if 'members' in self.cleaned_data:
            if len(self.cleaned_data['members']) < 2:
                raise forms.ValidationError("At least two members are required.")
            for member in self.cleaned_data['members']:
                if member.config['interface'] != self.cleaned_data['interface'].id:
                    self.add_error(
                        'members', f"{member} belongs to other DALI interface."
                    )
        self.group_addr = None
        if not self.instance.pk:
            from .controllers import DALIGearGroup
            occupied_addresses = set([
                int(c['config'].get('da', 0)) for c in Component.objects.filter(
                controller_uid=DALIGearGroup.uid,
                config__colonel=self.cleaned_data['colonel'].id,
                config__interface=self.cleaned_data['interface'].id,
            ).values('config')])
            for addr in range(16):
                if addr in occupied_addresses:
                    continue
                self.group_addr = addr
                break
            if self.group_addr is None:
                self.add_error(
                    'interface',
                    "Already has 16 groups. No more groups are allowed on DALI line."
                )
        else:
            self.group_addr = self.instance.config['da']
        if 'controls' in self.cleaned_data:
            self._clean_controls()
        return self.cleaned_data

    def save(self, commit=True):
        old_members = self.instance.config.get('members', [])
        self.instance.config['da'] = self.group_addr
        is_new = not self.instance.pk
        obj = super().save(commit)
        if commit:
            new_members = obj.config.get('members', [])
            for removed_member in Component.objects.filter(
                id__in=set(old_members) - set(new_members)
            ):
                self.controller._modify_member_group(
                    removed_member, self.group_addr, remove=True
                )
            for member in Component.objects.filter(id__in=new_members):
                self.controller._modify_member_group(member, self.group_addr)
            if is_new:
                GatewayObjectCommand(
                    obj.gateway, self.cleaned_data['colonel'],
                    command='finalize',
                    data={
                        'temp_id': 'none',
                        'permanent_id': obj.id,
                        'comp_config': {
                            'type': obj.controller_uid.split('.')[-1],
                            'family': self.controller.family,
                            'config': obj.config
                        }
                    }
                ).publish()
            else:
                GatewayObjectCommand(
                    obj.gateway, self.cleaned_data['colonel'], id=obj.id,
                    command='call', method='update_config', args=[
                        obj.controller._get_colonel_config()
                    ]
                ).publish()

        if commit:
            if self.cleaned_data.get('controls'):
                GatewayObjectCommand(
                    self.instance.gateway, obj, command='watch_buttons'
                ).publish()
            if self.instance.pk:
                old_controls = Component.objects.get(
                    pk=self.instance.pk
                ).config.get('controls')
                if old_controls != self.cleaned_data.get('controls'):
                    self.cleaned_data['colonel'].update_config()
        return obj


class DaliOccupancySensorConfigForm(DALIDeviceConfigForm, BaseComponentForm):
    hold_time = forms.TypedChoiceField(
        initial=3, coerce=int, choices=(
            (1, "10 s"), (2, "20 s"), (3, "30 s"), (4, "40 s"), (5, "50 s"),
            (6, "1 min"), (9, "1.5 min"), (12, "2 min"), (18, "3 min"),
            (30, "5 min"), (60, "10 min"), (120, "20 min"),
        )
    )


class DALILightSensorConfigForm(DALIDeviceConfigForm, BaseComponentForm):
    pass


class DALIButtonConfigForm(DALIDeviceConfigForm, BaseComponentForm):
    pass