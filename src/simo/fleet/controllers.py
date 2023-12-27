from django.core.exceptions import ValidationError
from simo.core.events import ObjectCommand
from simo.core.controllers import (
    BinarySensor as BaseBinarySensor,
    NumericSensor as BaseNumericSensor,
    Switch as BaseSwitch, Dimmer as BaseDimmer,
    MultiSensor as BaseMultiSensor, RGBWLight as BaseRGBWLight
)
from simo.conf import dynamic_settings
from simo.core.app_widgets import NumericSensorWidget
from simo.core.controllers import BEFORE_SEND, BEFORE_SET, ControllerBase
from simo.core.utils import easing
from simo.core.utils.helpers import heat_index
from simo.generic.controllers import Blinds as GenericBlinds
from .models import Colonel
from .gateways import FleetGatewayHandler
from .forms import (
    ColonelBinarySensorConfigForm, ColonelTouchSensorConfigForm,
    ColonelSwitchConfigForm, ColonelPWMOutputConfigForm,
    ColonelNumericSensorConfigForm, ColonelRGBLightConfigForm,
    ColonelDHTSensorConfigForm, DS18B20SensorConfigForm,
    BME680SensorConfigForm,
    DualMotorValveForm, BlindsConfigForm, BurglarSmokeDetectorConfigForm
)


class FleeDeviceMixin:

    def update_options(self, options):
        ObjectCommand(
            Colonel(id=self.component.config['colonel']),
            **{'command': 'update_options', 'id': self.component.id,
               'options': options}
        ).publish()

    def disable_controls(self):
        options = self.component.meta.get('options', {})
        if options.get('controls_enabled', True) != False:
            options['controls_enabled'] = False
            self.update_options(options)

    def enable_controls(self):
        options = self.component.meta.get('options', {})
        if options.get('controls_enabled', True) != True:
            options['controls_enabled'] = True
            self.update_options(options)


class BasicSensorMixin:
    gateway_class = FleetGatewayHandler

    def _get_occupied_pins(self):
        return [self.component.config['pin']]


class BinarySensor(FleeDeviceMixin, BasicSensorMixin, BaseBinarySensor):
    config_form = ColonelBinarySensorConfigForm


class BurglarSmokeDetector(BinarySensor):
    config_form = BurglarSmokeDetectorConfigForm
    name = 'Smoke Detector (Burglar)'

    def _get_occupied_pins(self):
        return [
            self.component.config['power_pin'],
            self.component.config['sensor_pin']
        ]


class AnalogSensor(FleeDeviceMixin, BasicSensorMixin, BaseNumericSensor):
    config_form = ColonelNumericSensorConfigForm
    name = "Analog sensor"


class DS18B20Sensor(FleeDeviceMixin, BasicSensorMixin, BaseNumericSensor):
    config_form = DS18B20SensorConfigForm
    name = "DS18B20 Temperature sensor"


class BaseClimateSensor(FleeDeviceMixin, BasicSensorMixin, BaseMultiSensor):
    app_widget = NumericSensorWidget

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sys_temp_units = 'C'
        if dynamic_settings['core__units_of_measure'] == 'imperial':
            self.sys_temp_units = 'F'

    @property
    def default_value(self):
        return [
            ['temperature', 0, self.sys_temp_units],
            ['humidity', 20, '%'],
            ['real_feel', 0, self.sys_temp_units]
        ]

    def _prepare_for_set(self, value):
        new_val = self.component.value.copy()

        new_val[0] = [
            'temperature', round(value.get('temp', 0), 1),
            self.sys_temp_units
        ]

        new_val[1] = ['humidity', round(value.get('hum', 50), 1), '%']

        if self.component.config.get('temperature_units', 'C') == 'C':
            if self.sys_temp_units == 'F':
                new_val[0][1] = round((new_val[0][1] * 9 / 5) + 32, 1)
        else:
            if self.sys_temp_units == 'C':
                new_val[0][1] = round((new_val[0][1] - 32) * 5 / 9, 1)

        real_feel = heat_index(
            new_val[0][1], new_val[1][1], self.sys_temp_units == 'F'
        )
        new_val[2] = ['real_feel', real_feel, self.sys_temp_units]
        return new_val


class DHTSensor(BaseClimateSensor):
    config_form = ColonelDHTSensorConfigForm
    name = "DHT climate sensor"


class BME680Sensor(BaseClimateSensor):
    config_form = BME680SensorConfigForm
    name = "BME680 Climate Sensor (I2C)"


class BasicOutputMixin:
    gateway_class = FleetGatewayHandler

    def _get_occupied_pins(self):
        pins = [self.component.config['output_pin']]
        for control_unit in self.component.config.get('controls', []):
            pins.append(control_unit['pin'])
        return pins

    def _send_to_device(self, value):
        ObjectCommand(
            Colonel(id=self.component.config['colonel']),
            **{'command': 'set_val', 'id': self.component.id, 'val': value}
        ).publish()


class Switch(FleeDeviceMixin, BasicOutputMixin, BaseSwitch):
    config_form = ColonelSwitchConfigForm


class PWMOutput(FleeDeviceMixin, BasicOutputMixin, BaseDimmer):
    name = "PWM Output"
    config_form = ColonelPWMOutputConfigForm

    # TODO: bring back min and max!

    def _prepare_for_send(self, value):
        conf = self.component.config
        if value >= conf.get('max', 100):
            value = conf.get('max', 100)
        elif value < conf.get('min', 0):
            value = conf.get('min', 0)

        if value == conf.get('max', 100):
            if conf.get('inverse'):
                pwm_value = 0
            else:
                pwm_value = 1023
        elif value == conf.get('min', 100):
            if conf.get('inverse'):
                pwm_value = 1023
            else:
                pwm_value = 0
        else:

            val_amplitude = conf.get('max', 100) - conf.get('min', 0)
            val_relative = value / val_amplitude
            pwm_amplitude = conf.get('duty_max', 1023) - conf.get('duty_min', 0.0)
            pwm_value = conf.get('duty_min', 0.0) + pwm_amplitude * val_relative

            if conf.get('inverse'):
                pwm_value = conf.get('duty_max', 1023) - pwm_value + conf.get('duty_min')

        return pwm_value

    def _prepare_for_set(self, pwm_value):
        conf = self.component.config
        if pwm_value > conf.get('duty_max', 1023):
            value = conf.get('max', 100)
        elif pwm_value < conf.get('duty_min', 0.0):
            value = conf.get('min', 0)
        else:
            pwm_amplitude = conf.get('duty_max', 1023) - conf.get('duty_min', 0.0)
            relative_value = (pwm_value - conf.get('duty_min', 0.0)) / pwm_amplitude
            val_amplitude = conf.get('max', 100) - conf.get('min', 0)
            value = conf.get('min', 0) + val_amplitude * relative_value

        if self.component.config.get('inverse'):
            value = conf.get('max', 100) - value + conf.get('min', 0)

        return value


class RGBLight(FleeDeviceMixin, BasicOutputMixin, BaseRGBWLight):
    config_form = ColonelRGBLightConfigForm


class DualMotorValve(FleeDeviceMixin, BaseSwitch):
    gateway_class = FleetGatewayHandler
    config_form = DualMotorValveForm
    name = "Dual Motor Valve"
    default_config = {}

    def _get_occupied_pins(self):
        return [
            self.component.config['open_pin'],
            self.component.config['close_pin']
        ]

    def _send_to_device(self, value):
        ObjectCommand(
            Colonel(id=self.component.config['colonel']),
            **{'command': 'set_val', 'id': self.component.id, 'val': value}
        ).publish()


class Blinds(FleeDeviceMixin, GenericBlinds):
    gateway_class = FleetGatewayHandler
    config_form = BlindsConfigForm

    def _get_occupied_pins(self):
        pins = [
            self.component.config['open_pin'],
            self.component.config['close_pin']
        ]
        for p in self.component.config.get('controls', []):
            pins.append(p['pin'])
        return pins

    def _send_to_device(self, value):
        ObjectCommand(
            Colonel(id=self.component.config['colonel']),
            **{'command': 'set_val', 'id': self.component.id, 'val': value}
        ).publish()



