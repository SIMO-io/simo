from django import forms
from django.utils.translation import gettext_lazy as _
from django.forms import formset_factory
from django.urls.base import get_script_prefix
from django.contrib.contenttypes.models import ContentType
from dal import autocomplete
from dal import forward
from simo.core.models import Component
from simo.core.forms import BaseComponentForm, ValueLimitForm, NumericSensorForm
from simo.core.utils.formsets import FormsetField
from simo.core.widgets import LogOutputWidget
from simo.core.utils.easing import EASING_CHOICES
from simo.core.utils.validators import validate_slaves
from simo.core.utils.admin import AdminFormActionForm
from .models import Colonel, ColonelPin, I2CInterface, i2c_interface_no_choices


class ColonelPinChoiceField(forms.ModelChoiceField):
    '''
    Required for API, so that SIMO app could properly handle
    fleet components configuration.
    '''
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


class I2CInterfaceAdminForm(forms.ModelForm):
    scl_pin = ColonelPinChoiceField(
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
    sda_pin = ColonelPinChoiceField(
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

    class Meta:
        model = I2CInterface
        fields = '__all__'

    def clean_scl_pin(self):
        if self.cleaned_data['scl_pin'].occupied_by \
        and self.cleaned_data['scl_pin'].occupied_by  != self.instance:
            raise forms.ValidationError(
                f"This pin is already occupied by "
                f"{self.cleaned_data['scl_pin'].occupied_by}!"
            )
        return self.cleaned_data['scl_pin']

    def clean_sda_pin(self):
        if self.cleaned_data['sda_pin'].occupied_by \
                and self.cleaned_data['sda_pin'].occupied_by != self.instance:
            raise forms.ValidationError(
                f"This pin is already occupied by "
                f"{self.cleaned_data['sda_pin'].occupied_by}!"
            )
        return self.cleaned_data['sda_pin']


class ColonelComponentForm(BaseComponentForm):
    colonel = forms.ModelChoiceField(
        label="Colonel", queryset=Colonel.objects.all(),
        help_text="ATENTION! Changing Colonel after component creation is not recommended!"
    )

    def clean_colonel(self):
        if not self.instance.pk:
            return self.cleaned_data['colonel']
        org = self.instance.config.get('colonel')
        if org and org != self.cleaned_data['colonel'].id:
            raise forms.ValidationError(
                "Changing colonel after component is created "
                "it is not allowed!"
            )
        return self.cleaned_data['colonel']

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
                if key == 'pin':
                    pin = ColonelPin.objects.get(
                        id=self.cleaned_data['controls'][i]['pin']
                    )
                    pin_instances[i] = pin
                    updated_vals['pin_no'] = pin.no
                elif key == 'touch_threshold':
                    updated_vals[key] = int(val)
            self.cleaned_data['controls'][i] = updated_vals

        formset_errors = {}
        for i, control in enumerate(self.cleaned_data['controls']):
            if pin_instances[i].colonel != self.cleaned_data['colonel']:
                formset_errors[i] = {
                    'pin': f"{pin_instances[i]} must be from the same Colonel!"
                }
            elif pin_instances[i].occupied_by \
            and pin_instances[i].occupied_by != self.instance:
                formset_errors[i] = {
                    'pin': f"{pin_instances[i]} is already occupied by {pin_instances[i].occupied_by}!"
                }

        errors_list = []
        if formset_errors:
            for i, control in enumerate(self.cleaned_data['controls']):
                errors_list.append(formset_errors.get(i, {}))
        if errors_list:
            self._errors['controls'] = errors_list
            if 'controls' in self.cleaned_data:
                del self.cleaned_data['controls']

    def save(self, commit=True):
        obj = super().save(commit)
        if commit:
            self.cleaned_data['colonel'].components.add(obj)
            self.cleaned_data['colonel'].rebuild_occupied_pins()
            self.cleaned_data['colonel'].save()
            self.cleaned_data['colonel'].update_config()
        return obj


class ControlPinForm(forms.Form):
    pin = ColonelPinChoiceField(
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
    active = forms.ChoiceField(required=True, choices=(
        ('LOW', 'LOW'), ('HIGH', 'HIGH')
    ), initial='LOW')
    method = forms.ChoiceField(
        required=True, choices=(
            ('momentary', "Momentary"), ('toggle', "Toggle"),
        ),
    )
    prefix = 'controls'


class ColonelBinarySensorConfigForm(ColonelComponentForm):
    pin = ColonelPinChoiceField(
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
    pull = forms.ChoiceField(
        choices=(
            ('HIGH', "HIGH"), ('LOW', "LOW"), ("FLOATING", "leave floating"),
        ),
        help_text="If you are not sure what is this all about, "
                  "you are most definitely want to pull this HIGH or LOW "
                  "but not leave it floating!"
    )
    inverse = forms.TypedChoiceField(
        choices=((1, "Yes"), (0, "No")), coerce=int,
        help_text="Hint: Set pull HIGH and inverse to Yes, to get ON signal when "
                  "you deliver GND to the pin and OFF when you cut it out."
    )
    debounce = forms.IntegerField(
        min_value=0, max_value=1000 * 60 * 60, required=False, initial=0,
        help_text="Some sensors are unstable and quickly transition "
                  "between ON/OFF states when engaged. <br>"
                  "Set debounce value in milliseconds, to remediate this. "
                  "100ms offers a good starting point!"

    )

    def clean(self):
        super().clean()
        if not self.cleaned_data.get('colonel'):
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
        self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)


class ColonelNumericSensorConfigForm(ColonelComponentForm, NumericSensorForm):
    pin = ColonelPinChoiceField(
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
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data

        self._clean_pin('pin')

        return self.cleaned_data


    def save(self, commit=True):
        self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)


class DS18B20SensorConfigForm(ColonelComponentForm, NumericSensorForm):
    pin = ColonelPinChoiceField(
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
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data

        self._clean_pin('pin')

        return self.cleaned_data

    def save(self, commit=True):
        self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)



class ColonelDHTSensorConfigForm(ColonelComponentForm):
    pin = ColonelPinChoiceField(
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
        self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)


class BME680SensorConfigForm(ColonelComponentForm):
    i2c_interface = forms.TypedChoiceField(
        coerce=int, choices=i2c_interface_no_choices,
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-i2c_interfaces',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
            ]
        )
    )
    i2c_address = forms.IntegerField(
        min_value=0, max_value=127, initial=118,
        help_text="Integer: 0 - 127. Dafault: 118"
    )
    read_frequency_s = forms.IntegerField(
        initial=60, min_value=1, max_value=60*60*24,
        help_text='read and report climate value every s. '
                              'Can not be less than 1s.'

    )


class MPC9808SensorConfigForm(ColonelComponentForm):
    i2c_interface = forms.TypedChoiceField(
        coerce=int, choices=i2c_interface_no_choices,
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-i2c_interfaces',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
            ]
        )
    )
    i2c_address = forms.IntegerField(
        min_value=0, max_value=127, initial=24,
        help_text="Integer: 0 - 127. Default: 24",
    )
    read_frequency_s = forms.IntegerField(
        initial=60, min_value=1, max_value=60 * 60 * 24,
        help_text='read and report temperature value every s. '
                  'Can not be less than 1s.'

    )


class ColonelTouchSensorConfigForm(ColonelComponentForm):
    pin = ColonelPinChoiceField(
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
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data

        self._clean_pin('pin')

        return self.cleaned_data


    def save(self, commit=True):
        self.instance.config['pin_no'] = self.cleaned_data['pin'].no
        return super().save(commit=commit)


class ColonelSwitchConfigForm(ColonelComponentForm):
    output_pin = ColonelPinChoiceField(
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
    engaged_action = forms.ChoiceField(
        choices=(('HIGH', "HIGH"), ('LOW', "LOW")),
    )
    auto_off = forms.FloatField(
        required=False, min_value=0.01, max_value=1000000000,
        help_text="If provided, switch will be turned off after "
                  "given amount of seconds after every turn on event."
    )
    inverse = forms.BooleanField(
        label=_("Inverse switch value"), required=False
    )
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
            ControlPinForm, can_delete=True, can_order=True, extra=0, max_num=1
        )
    )

    def clean_slaves(self):
        if not self.cleaned_data['slaves'] or not self.instance:
            return self.cleaned_data['slaves']
        return validate_slaves(self.cleaned_data['slaves'], self.instance)


    def clean(self):
        super().clean()
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if not self.cleaned_data.get('output_pin'):
            return self.cleaned_data

        self._clean_pin('output_pin')

        if not self.cleaned_data.get('controls'):
            return self.cleaned_data

        self._clean_controls()

        return self.cleaned_data


    def save(self, commit=True):
        self.instance.config['output_pin_no'] = self.cleaned_data['output_pin'].no
        return super().save(commit=commit)


class ColonelPWMOutputConfigForm(ColonelComponentForm):
    output_pin = ColonelPinChoiceField(
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
    frequency = forms.IntegerField(
        min_value=30, max_value=100000, required=True, initial=3000,
        help_text="PWM signal frequency in Hz. Works only with GPIO ports."
                  "3000 Hz offers great performance in most use cases."

    )
    min = forms.FloatField(
        required=True, initial=0,
        help_text="Minimum component value"
    )
    max = forms.FloatField(
        required=True, initial=100,
        help_text="Maximum component value"
    )
    duty_min = forms.IntegerField(
        min_value=0, max_value=1023, required=True, initial=0,
        help_text="Minumum PWM signal output duty (0 - 1023)"
    )
    duty_max = forms.IntegerField(
        min_value=0, max_value=1023, required=True, initial=1023,
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
        help_text="Component ON value when used with toggle switch"
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
            ControlPinForm, can_delete=True, can_order=True, extra=0, max_num=1
        )
    )

    def clean_slaves(self):
        if not self.cleaned_data['slaves'] or not self.instance:
            return self.cleaned_data['slaves']
        return validate_slaves(self.cleaned_data['slaves'], self.instance)

    def clean(self):
        super().clean()
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if not self.cleaned_data.get('output_pin'):
            return self.cleaned_data

        self._clean_pin('output_pin')

        if not self.cleaned_data.get('controls'):
            return self.cleaned_data

        self._clean_controls()

        return self.cleaned_data


    def save(self, commit=True):
        self.instance.config['output_pin_no'] = self.cleaned_data['output_pin'].no
        return super().save(commit=commit)


class ColonelRGBLightConfigForm(ColonelComponentForm):
    output_pin = ColonelPinChoiceField(
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
    timing = forms.TypedChoiceField(
        initial=1, coerce=int, choices=((1, "800kHz (most common)"), (0, "400kHz"),)
    )
    order = forms.ChoiceField(
        initial='RGB', choices=(
            ("RGB", "RGB"), ("RBG", "RBG"), ("GRB", "GRB"),
            ("RGBW", "RGBW"), ("RBGW", "RBGW"), ("GRBW", "GRBW"),
        )
    )
    controls = FormsetField(
        formset_factory(
            ControlPinForm, can_delete=True, can_order=True, extra=0, max_num=2
        )
    )

    def save(self, commit=True):
        self.instance.config['output_pin_no'] = self.cleaned_data['output_pin'].no
        if len(self.cleaned_data['order']) > 3:
            self.instance.config['has_white'] = True
        else:
            self.instance.config['has_white'] = False
        return super().save(commit)


    def clean(self):
        super().clean()
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if not self.cleaned_data.get('output_pin'):
            return self.cleaned_data

        self._clean_pin('output_pin')

        if not self.cleaned_data.get('controls'):
            return self.cleaned_data

        self._clean_controls()

        return self.cleaned_data



class DualMotorValveForm(ColonelComponentForm):
    open_pin = ColonelPinChoiceField(
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
        help_text="Time in seconds to open."
    )
    close_pin = ColonelPinChoiceField(
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
        help_text="Time in seconds to close."
    )


    def clean(self):
        super().clean()
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if not self.cleaned_data.get('open_pin'):
            return self.cleaned_data
        if not self.cleaned_data.get('close_pin'):
            return self.cleaned_data

        self._clean_pin('open_pin')
        self._clean_pin('close_pin')

        return self.cleaned_data

    def save(self, commit=True):
        self.instance.config['open_pin_no'] = self.cleaned_data['open_pin'].no
        self.instance.config['close_pin_no'] = self.cleaned_data['close_pin'].no
        return super().save(commit=commit)


class BlindsConfigForm(ColonelComponentForm):
    open_pin = ColonelPinChoiceField(
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
            ControlPinForm, can_delete=True, can_order=True, extra=0, max_num=2
        )
    )

    def clean(self):
        super().clean()
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if not self.cleaned_data.get('open_pin'):
            return self.cleaned_data
        if not self.cleaned_data.get('close_pin'):
            return self.cleaned_data

        self._clean_pin('open_pin')
        self._clean_pin('close_pin')

        if 'controls' not in self.cleaned_data:
            return self.cleaned_data

        if len(self.cleaned_data['controls']) not in (0, 2):
            self.add_error('controls', "Must have 0 or 2 controls")
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

        return self.cleaned_data

    def save(self, commit=True):
        self.instance.config['open_pin_no'] = self.cleaned_data['open_pin'].no
        self.instance.config['close_pin_no'] = self.cleaned_data['close_pin'].no
        return super().save(commit=commit)


class BurglarSmokeDetectorConfigForm(ColonelComponentForm):
    power_pin = ColonelPinChoiceField(
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
    power_action = forms.ChoiceField(
        choices=(('HIGH', "HIGH"), ('LOW', "LOW")),
    )
    sensor_pin = ColonelPinChoiceField(
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
    sensor_pull = forms.ChoiceField(
        choices=(
            ('HIGH', "HIGH"), ('LOW', "LOW"), ("FLOATING", "leave floating"),
        ),
        help_text="If you are not sure what is this all about, "
                  "you are most definitely want to pull this HIGH or LOW "
                  "but not leave it floating!"
    )
    sensor_inverse = forms.TypedChoiceField(
        choices=((1, "Yes"), (0, "No")), coerce=int,
        help_text="Hint: Set pull HIGH and inverse to Yes, to get ON signal when "
                  "you deliver GND to the pin and OFF when you cut it out."
    )


    def clean(self):
        super().clean()
        if not self.cleaned_data.get('colonel'):
            return self.cleaned_data
        if 'sensor_pin' not in self.cleaned_data:
            return self.cleaned_data
        if 'power_pin' not in self.cleaned_data:
            return self.cleaned_data

        self._clean_pin('sensor_pin')
        self._clean_pin('power_pin')


        if self.cleaned_data['sensor_pin'].no > 100:
            if self.cleaned_data['sensor_pin'].no < 126:
                if self.cleaned_data.get('sensor_pull') == 'HIGH':
                    self.add_error(
                        'sensor_pull',
                        "Sorry, but this pin is already pulled LOW and "
                        "it can not be changed by this setting. "
                        "Please use 5kohm resistor to physically pull it HIGH "
                        "if that's what you want to do."
                    )
            else:
                if self.cleaned_data.get('sensor_pull') == 'LOW':
                    self.add_error(
                        'sensor_pull',
                        "Sorry, but this pin is already pulled HIGH and "
                        "it can not be changed by this setting. "
                        "Please use 5kohm resistor to physically pull it LOW "
                        "if that's what you want to do."
                    )
        elif self.cleaned_data.get('sensor_pull') != 'FLOATING':
            if not self.cleaned_data['sensor_pin'].output:
                self.add_error(
                    'sensor_pin',
                    f"Sorry, but {self.cleaned_data['sensor_pin']} "
                    f"does not have internal pull HIGH/LOW"
                    " resistance capability"
                )

        return self.cleaned_data

    def save(self, commit=True):
        self.instance.config['sensor_pin_no'] = self.cleaned_data['sensor_pin'].no
        self.instance.config['power_pin_no'] = self.cleaned_data['power_pin'].no
        return super().save(commit=commit)


class TTLockConfigForm(ColonelComponentForm):
    pass

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
        if commit:
            self.cleaned_data['colonel'].components.add(obj)
            self.cleaned_data['colonel'].save()
        return obj

