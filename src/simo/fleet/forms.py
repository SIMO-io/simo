from django import forms
from django.utils.translation import gettext_lazy as _
from django.forms import formset_factory
from django.urls.base import get_script_prefix
from django.contrib.contenttypes.models import ContentType
from dal import autocomplete
from dal import forward
from simo.core.forms import BaseComponentForm, ValueLimitForm, NumericSensorForm
from simo.core.utils.formsets import FormsetField
from simo.core.widgets import LogOutputWidget
from simo.core.utils.easing import EASING_CHOICES
from .models import Colonel, I2CInterface, i2c_interface_no_choices
from .utils import get_gpio_pins_choices, get_available_gpio_pins


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


class MoveColonelForm(forms.Form):
    colonel = forms.ModelChoiceField(
        label="Move to:", queryset=Colonel.objects.filter(components=None),
    )


class I2CInterfaceAdminForm(forms.ModelForm):
    scl_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'output': True}, 'filters')
            ]
        )
    )
    sda_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'output': True}, 'filters')
            ]
        )
    )

    class Meta:
        model = I2CInterface
        fields = '__all__'

    def clean_scl_pin(self):
        initial = None
        if self.instance.pk:
            initial = self.instance.scl_pin
        available_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'output': True},
            selected=initial
        )
        if self.cleaned_data['scl_pin'] not in available_pins:
            raise forms.ValidationError("Pin is unavailable.")
        return self.cleaned_data['scl_pin']

    def clean_sda_pin(self):
        initial = None
        if self.instance.pk:
            initial = self.instance.sda_pin
        available_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'output': True},
            selected=initial
        )
        if self.cleaned_data['sda_pin'] not in available_pins:
            raise forms.ValidationError("Pin is unavailable.")

        if self.cleaned_data.get('scl_pin') == self.cleaned_data['sda_pin']:
            raise forms.ValidationError("Can not be the same as SCL pin!")

        return self.cleaned_data['sda_pin']


class ColonelComponentForm(BaseComponentForm):
    colonel = forms.ModelChoiceField(
        label="Colonel", queryset=Colonel.objects.all(),
        help_text="ATENTION! Changing Colonel after component creation is not recommended!"
    )

    # def clean_colonel(self):
    #     org = self.instance.config.get('colonel')
    #     if org and org != self.cleaned_data['colonel'].id:
    #         raise forms.ValidationError(
    #             "Changing colonel after component is created "
    #             "it is not allowed."
    #         )
    #     return self.cleaned_data['colonel']

    def save(self, commit=True):
        obj = super().save(commit)
        if commit:
            self.cleaned_data['colonel'].components.add(obj)
            self.cleaned_data['colonel'].rebuild_occupied_pins()
            self.cleaned_data['colonel'].save()
            self.cleaned_data['colonel'].update_config()
        return obj


class ControlPinForm(forms.Form):
    pin = forms.TypedChoiceField(
        coerce=int, required=True, choices=get_gpio_pins_choices,
        help_text="Use this if you also want to wire up a wall switch",
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
            ('touch', "Touch")
        ),
    )
    touch_threshold = forms.IntegerField(
        min_value=0, max_value=999999999, required=False, initial=1000,
        help_text="Used to detect touch events. "
                  "Smaller value means a higher sensitivity. "
                  "1000 offers good starting point. <br> "
                  "Used only when controll method is set to Touch."

    )
    prefix = 'controls'


class ColonelBinarySensorConfigForm(ColonelComponentForm):
    pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
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
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data
        if self.instance.pk:
            selected = self.instance.config.get('pin')
        else:
            selected = None
        input_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'input': True},
            selected=selected
        )
        if self.cleaned_data['pin'] not in input_pins:
            self.add_error(
                'pin',
                "Sorry, but GPIO%d pin can not be used as input pin "
                % self.cleaned_data['pin']
            )
            return
        if self.cleaned_data['pin'] > 100:
            if self.cleaned_data['pin'] < 126:
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
            pins_available_for_pull = get_available_gpio_pins(
                self.cleaned_data['colonel'], filters={'output': True},
                selected=selected
            )
            if self.cleaned_data['pin'] not in pins_available_for_pull:
                self.add_error(
                    'pin',
                    "Sorry, but GPIO%d pin does not have internal pull HIGH/LOW"
                    " resistance capability" % self.cleaned_data['pin']
                )
                return

        return self.cleaned_data


class ColonelNumericSensorConfigForm(ColonelComponentForm, NumericSensorForm):
    pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'adc': True}, 'filters')
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
        if self.instance.pk:
            selected = self.instance.config.get('pin')
        else:
            selected = None
        input_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'adc': True},
            selected=selected
        )
        if self.cleaned_data['pin'] not in input_pins:
            self.add_error(
                'pin',
                "Sorry, but GPIO%d pin can not be used as ADC input pin "
                % self.cleaned_data['pin']
            )
            return
        return self.cleaned_data


class DS18B20SensorConfigForm(ColonelComponentForm):
    pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'input': True, 'native': True}, 'filters')
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
        if self.instance.pk:
            selected = self.instance.config.get('pin')
        else:
            selected = None
        input_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'adc': True},
            selected=selected
        )
        if self.cleaned_data['pin'] not in input_pins:
            self.add_error(
                'pin',
                "Sorry, but GPIO%d pin can not be used"
                % self.cleaned_data['pin']
            )
            return
        return self.cleaned_data


class ColonelDHTSensorConfigForm(ColonelComponentForm):
    pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'input': True, 'native': True}, 'filters')
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
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data
        if self.instance.pk:
            selected = self.instance.config.get('pin')
        else:
            selected = None
        input_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'adc': True},
            selected=selected
        )
        if self.cleaned_data['pin'] not in input_pins:
            self.add_error(
                'pin',
                "Sorry, but GPIO%d pin can not be used"
                % self.cleaned_data['pin']
            )
            return
        return self.cleaned_data


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
        help_text="Integer: 0 - 127", min_value=0, max_value=127
    )
    read_frequency_s = forms.IntegerField(
        initial=60, min_value=1, max_value=60*60*24,
        help_text='read and report climate value every s. '
                              'Can not be less than 1s.'

    )


class ColonelTouchSensorConfigForm(ColonelComponentForm):
    pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
        widget=autocomplete.ListSelect2(
            url='autocomplete-colonel-pins',
            forward=[
                forward.Self(),
                forward.Field('colonel'),
                forward.Const({'capacitive': True}, 'filters')
            ]
        )
    )
    threshold = forms.IntegerField(
        min_value=0, max_value=999999999, required=False, initial=1000,
        help_text="Used to detect touch events. "
                  "Smaller value means a higher sensitivity. "
                  "1000 offers good starting point."

    )
    inverse = forms.ChoiceField(choices=(('no', "No"), ('yes', "Yes")))

    def clean(self):
        super().clean()
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if 'pin' not in self.cleaned_data:
            return self.cleaned_data
        if self.instance.pk:
            selected = self.instance.config.get('pin')
        else:
            selected = None
        free_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], selected=selected
        )
        if self.cleaned_data['pin'] not in free_pins:
            self.add_error(
                'pin',
                "Sorry, but GPIO%d pin is occupied."
                % self.cleaned_data['pin']
            )
            return
        touch_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'capacitive': True},
            selected=selected
        )
        if self.cleaned_data['pin'] not in touch_pins:
            self.add_error(
                'pin',
                "Sorry, but GPIO%d pin can not be used as input pin "
                % self.cleaned_data['pin']
            )
            return
        return self.cleaned_data


class ColonelSwitchConfigForm(ColonelComponentForm):
    output_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
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

    controls = FormsetField(
        formset_factory(
            ControlPinForm, can_delete=True, can_order=True, extra=0, max_num=1
        )
    )

    def clean(self):
        super().clean()
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if not self.cleaned_data.get('output_pin'):
            return self.cleaned_data
        if self.instance.pk:
            selected = self.instance.config.get('output_pin')
        else:
            selected = None
        output_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'output': True},
            selected=selected
        )
        if self.cleaned_data['output_pin'] not in output_pins:
            self.add_error(
                'output_pin',
                "Sorry, but GPIO%d pin can not be used as output pin "
                % self.cleaned_data['output_pin']
            )
            return self.cleaned_data

        if 'controls' not in self.cleaned_data:
            return self.cleaned_data

        # TODO: Formset factory should return proper field value types instead of str type
        for i, control in enumerate(self.cleaned_data['controls']):
            for key, val in control.items():
                if key in ('pin', 'touch_threshold'):
                    self.cleaned_data['controls'][i][key] = int(val)
                else:
                    self.cleaned_data['controls'][i][key] = val

        for i, control in enumerate(self.cleaned_data['controls']):
            try:
                selected = self.instance.config['controls'][i]['pin']
            except:
                selected = None
            free_pins = get_available_gpio_pins(
                self.cleaned_data['colonel'], filters={'input': True},
                selected=selected
            )
            if control['pin'] not in free_pins:
                self.add_error(
                    'controls',
                    "Sorry, but GPIO%d pin is occupied."
                    % control['pin']
                )
                return

        return self.cleaned_data


class ColonelPWMOutputConfigForm(ColonelComponentForm):
    output_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
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
        label=_("Inverse dimmer signal"), required=False
    )
    on_value = forms.FloatField(
        required=True, initial=100,
        help_text="Component ON value when used with toggle switch"
    )
    controls = FormsetField(
        formset_factory(
            ControlPinForm, can_delete=True, can_order=True, extra=0, max_num=1
        )
    )

    def clean(self):
        super().clean()
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if not self.cleaned_data.get('output_pin'):
            return self.cleaned_data
        if self.instance.pk:
            selected = self.instance.config.get('output_pin')
        else:
            self.cleaned_data['value_units'] = '%'
            selected = None
        output_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'output': True},
            selected=selected
        )
        if self.cleaned_data['output_pin'] not in output_pins:
            self.add_error(
                'output_pin',
                "Sorry, but GPIO%d pin can not be used as output pin "
                % self.cleaned_data['output_pin']
            )
            return self.cleaned_data

        if 'controls' not in self.cleaned_data:
            return self.cleaned_data


        # TODO: Formset factory should return proper field value types instead of str type
        for i, control in enumerate(self.cleaned_data['controls']):
            for key, val in control.items():
                if key in ('pin', 'touch_threshold'):
                    self.cleaned_data['controls'][i][key] = int(val)
                else:
                    self.cleaned_data['controls'][i][key] = val

        for i, control in enumerate(self.cleaned_data['controls']):
            try:
                selected = self.instance.config['controls'][i]['pin']
            except:
                selected = None
            free_pins = get_available_gpio_pins(
                self.cleaned_data['colonel'], filters={'input': True},
                selected=selected
            )
            if control['pin'] not in free_pins:
                self.add_error(
                    'controls',
                    "Sorry, but GPIO%d pin is occupied."
                    % control['pin']
                )
                return

        return self.cleaned_data


class ColonelRGBLightConfigForm(ColonelComponentForm):
    output_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
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
        if len(self.cleaned_data['order']) > 3:
            self.instance.config['has_white'] = True
        else:
            self.instance.config['has_white'] = False
        return super().save(commit)


    def clean(self):
        super().clean()
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if not self.cleaned_data.get('output_pin'):
            return self.cleaned_data
        if self.instance.pk:
            selected = self.instance.config.get('output_pin')
        else:
            self.cleaned_data['value_units'] = '%'
            selected = None
        output_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'output': True, 'native': True},
            selected=selected
        )
        if self.cleaned_data['output_pin'] not in output_pins:
            self.add_error(
                'output_pin',
                "Sorry, but GPIO%d pin can not be used as output pin "
                % self.cleaned_data['output_pin']
            )
            return self.cleaned_data

        if 'controls' not in self.cleaned_data:
            return self.cleaned_data


        # TODO: Formset factory should return proper field value types instead of str type
        for i, control in enumerate(self.cleaned_data['controls']):
            for key, val in control.items():
                if key in ('pin', 'touch_threshold'):
                    self.cleaned_data['controls'][i][key] = int(val)
                else:
                    self.cleaned_data['controls'][i][key] = val

        for i, control in enumerate(self.cleaned_data['controls']):
            try:
                selected = self.instance.config['controls'][i]['pin']
            except:
                selected = None
            free_pins = get_available_gpio_pins(
                self.cleaned_data['colonel'], filters={'input': True},
                selected=selected
            )
            if control['pin'] not in free_pins:
                self.add_error(
                    'controls',
                    "Sorry, but GPIO%d pin is occupied."
                    % control['pin']
                )
                return

        return self.cleaned_data


class DualMotorValveForm(ColonelComponentForm):
    open_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
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
    close_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
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
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if not self.cleaned_data.get('open_pin'):
            return self.cleaned_data
        if not self.cleaned_data.get('close_pin'):
            return self.cleaned_data

        if self.instance.pk:
            selected = self.instance.config.get('open_pin')
        else:
            selected = None
        output_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'output': True},
            selected=selected
        )
        if self.cleaned_data['open_pin'] not in output_pins:
            self.add_error(
                'open_pin',
                "Sorry, but GPIO%d pin can not be used as output pin "
                % self.cleaned_data['open_pin']
            )
            return

        if self.instance.pk:
            selected = self.instance.config.get('close_pin')
        else:
            selected = None
        output_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'output': True},
            selected=selected
        )
        if self.cleaned_data['close_pin'] not in output_pins:
            self.add_error(
                'close_pin',
                "Sorry, but GPIO%d pin can not be used as output pin "
                % self.cleaned_data['close_pin']
            )
            return
        return self.cleaned_data


class BlindsConfigForm(ColonelComponentForm):
    open_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
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
    close_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
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
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if not self.cleaned_data.get('open_pin'):
            return self.cleaned_data
        if not self.cleaned_data.get('close_pin'):
            return self.cleaned_data

        if self.instance.pk:
            selected = self.instance.config.get('open_pin')
        else:
            selected = None
        output_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'],
            filters={'output': True},
            selected=selected
        )
        if self.cleaned_data['open_pin'] not in output_pins:
            self.add_error(
                'open_pin',
                "Sorry, but GPIO%d pin can not be used as output pin "
                % self.cleaned_data['open_pin']
            )
            return

        if self.instance.pk:
            selected = self.instance.config.get('close_pin')
        else:
            selected = None
        output_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'],
            filters={'output': True},
            selected=selected
        )
        if self.cleaned_data['close_pin'] not in output_pins:
            self.add_error(
                'close_pin',
                "Sorry, but GPIO%d pin can not be used as output pin "
                % self.cleaned_data['close_pin']
            )
            return


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


        # TODO: Formset factory should return proper field value types instead of str type
        for i, control in enumerate(self.cleaned_data['controls']):
            for key, val in control.items():
                if key in ('pin', 'touch_threshold'):
                    self.cleaned_data['controls'][i][key] = int(val)
                else:
                    self.cleaned_data['controls'][i][key] = val

        for i, control in enumerate(self.cleaned_data['controls']):
            try:
                selected = self.instance.config['controls'][i]['pin']
            except:
                selected = None
            free_pins = get_available_gpio_pins(
                self.cleaned_data['colonel'], filters={'input': True},
                selected=selected
            )
            if control['pin'] not in free_pins:
                self.add_error(
                    'controls',
                    "Sorry, but GPIO%d pin is occupied."
                    % control['pin']
                )
                return

        return self.cleaned_data


class BurglarSmokeDetectorConfigForm(ColonelComponentForm):
    power_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
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
    sensor_pin = forms.TypedChoiceField(
        coerce=int, choices=get_gpio_pins_choices,
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
        if 'colonel' not in self.cleaned_data:
            return self.cleaned_data
        if 'sensor_pin' not in self.cleaned_data:
            return self.cleaned_data
        if 'power_pin' not in self.cleaned_data:
            return self.cleaned_data


        if self.instance.pk:
            selected = self.instance.config.get('power_pin')
        else:
            selected = None
        output_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'output': True},
            selected=selected
        )
        if self.cleaned_data['power_pin'] not in output_pins:
            self.add_error(
                'output_pin',
                "Sorry, but GPIO%d pin can not be used as output pin "
                % self.cleaned_data['power_pin']
            )
            return self.cleaned_data



        if self.instance.pk:
            selected = self.instance.config.get('sensor_pin')
        else:
            selected = None
        input_pins = get_available_gpio_pins(
            self.cleaned_data['colonel'], filters={'input': True},
            selected=selected
        )
        if self.cleaned_data['sensor_pin'] not in input_pins:
            self.add_error(
                'pin',
                "Sorry, but GPIO%d pin can not be used as input pin "
                % self.cleaned_data['pin']
            )
            return
        if self.cleaned_data['sensor_pin'] > 100:
            if self.cleaned_data['sensor_pin'] < 126:
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
            pins_available_for_pull = get_available_gpio_pins(
                self.cleaned_data['colonel'], filters={'output': True},
                selected=selected
            )
            if self.cleaned_data['sensor_pin'] not in pins_available_for_pull:
                self.add_error(
                    'pin',
                    "Sorry, but GPIO%d pin does not have internal pull HIGH/LOW"
                    " resistance capability" % self.cleaned_data['sensor_pin']
                )
                return

        return self.cleaned_data



#
# class ColonelBLEClimateSensorConfigForm(
#     ColonelComponentMixin, BaseComponentForm
# ):
#     colonel = forms.ModelChoiceField(queryset=Colonel.objects.all())
#     ble_device = forms.ModelChoiceField(
#         queryset=BLEDevice.objects.filter(
#             type=BLE_DEVICE_TYPE_GOVEE_MULTISENSOR
#         )
#     )
#     additional_fields = ('colonel', 'ble_device')
#
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         qs = self.fields['ble_device'].queryset
#         if self.instance.pk:
#             self.fields['ble_device'].queryset = qs.filter(
#                 Q(component__isnull=True) | Q(component=self.instance)
#             )
#         else:
#             self.fields['ble_device'].queryset = qs.filter(component__isnull=True)
#
#     def clean(self):
#         colonel_ble_devices = self.cleaned_data['colonel'].ble_devices.all()
#         if self.cleaned_data['ble_device'] not in colonel_ble_devices:
#             available_colonels = self.cleaned_data['ble_device'].colonels.all()
#             self.add_error(
#                 'ble_device',
#                 _("This BLE device is available only on colonel%s: %s" %
#                   (
#                       's' if len(available_colonels) > 1 else '',
#                       ', '.join([str(c) for c in available_colonels])
#                   )
#                 )
#             )
#         return self.cleaned_data
