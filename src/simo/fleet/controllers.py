from django.utils.translation import gettext_lazy as _
from simo.core.events import GatewayObjectCommand
from simo.core.controllers import (
    BinarySensor as BaseBinarySensor,
    NumericSensor as BaseNumericSensor,
    Switch as BaseSwitch, Dimmer as BaseDimmer,
    MultiSensor as BaseMultiSensor, RGBWLight as BaseRGBWLight
)
from simo.conf import dynamic_settings
from simo.core.app_widgets import NumericSensorWidget
from simo.core.controllers import Lock
from simo.core.utils.helpers import heat_index
from simo.core.utils.serialization import (
    serialize_form_data, deserialize_form_data
)
from simo.generic.controllers import Blinds as GenericBlinds
from .models import Colonel
from .gateways import FleetGatewayHandler
from .forms import (
    ColonelPinChoiceField,
    ColonelBinarySensorConfigForm, ColonelTouchSensorConfigForm,
    ColonelSwitchConfigForm, ColonelPWMOutputConfigForm,
    ColonelNumericSensorConfigForm, ColonelRGBLightConfigForm,
    ColonelDHTSensorConfigForm, DS18B20SensorConfigForm,
    BME680SensorConfigForm, MPC9808SensorConfigForm,
    DualMotorValveForm, BlindsConfigForm, BurglarSmokeDetectorConfigForm,
    TTLockConfigForm
)


class FleeDeviceMixin:

    def update_options(self, options):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            command='update_options',
            id=self.component.id,
            options=options
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

    def _get_colonel_config(self):
        declared_fields = self.config_form.declared_fields
        config = {}
        for key, val in self.component.config.items():
            if key == 'colonel':
                continue
            if val in ({}, [], None):
                continue
            if isinstance(declared_fields.get(key), ColonelPinChoiceField):
                config[f'{key}_no'] = self.component.config[f'{key}_no']
            else:
                config[key] = val
        return config


class BasicSensorMixin:
    gateway_class = FleetGatewayHandler



class BinarySensor(FleeDeviceMixin, BasicSensorMixin, BaseBinarySensor):
    config_form = ColonelBinarySensorConfigForm

    def _get_occupied_pins(self):
        return [
            self.component.config['pin_no'],
        ]


class BurglarSmokeDetector(BinarySensor):
    config_form = BurglarSmokeDetectorConfigForm
    name = 'Smoke Detector (Burglar)'

    def _get_occupied_pins(self):
        return [
            self.component.config['power_pin_no'],
            self.component.config['sensor_pin_no']
        ]


class AnalogSensor(FleeDeviceMixin, BasicSensorMixin, BaseNumericSensor):
    config_form = ColonelNumericSensorConfigForm
    name = "Analog sensor"

    def _get_occupied_pins(self):
        return [
            self.component.config['pin_no'],
        ]


class DS18B20Sensor(FleeDeviceMixin, BasicSensorMixin, BaseNumericSensor):
    config_form = DS18B20SensorConfigForm
    name = "DS18B20 Temperature sensor"

    def _get_occupied_pins(self):
        return [
            self.component.config['pin_no'],
        ]


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

    def _get_occupied_pins(self):
        return [
            self.component.config['pin_no'],
        ]


class BME680Sensor(BaseClimateSensor):
    config_form = BME680SensorConfigForm
    name = "BME680 Climate Sensor (I2C)"


class MPC9808TempSensor(FleeDeviceMixin, BasicSensorMixin, BaseNumericSensor):
    config_form = MPC9808SensorConfigForm
    name = "MPC9808 Temperature Sensor (I2C)"



class BasicOutputMixin:
    gateway_class = FleetGatewayHandler

    def _get_occupied_pins(self):
        pins = [self.component.config['output_pin_no']]
        for control_unit in self.component.config.get('controls', []):
            pins.append(control_unit['pin_no'])
        return pins

    def _send_to_device(self, value):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            set_val=value,
            component_id=self.component.id,
        ).publish()


class Switch(FleeDeviceMixin, BasicOutputMixin, BaseSwitch):
    config_form = ColonelSwitchConfigForm


class PWMOutput(FleeDeviceMixin, BasicOutputMixin, BaseDimmer):
    name = "PWM Output"
    config_form = ColonelPWMOutputConfigForm

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


class DualMotorValve(FleeDeviceMixin, BasicOutputMixin, BaseSwitch):
    gateway_class = FleetGatewayHandler
    config_form = DualMotorValveForm
    name = "Dual Motor Valve"
    default_config = {}

    def _get_occupied_pins(self):
        return [
            self.component.config['open_pin_no'],
            self.component.config['close_pin_no']
        ]


class Blinds(FleeDeviceMixin, BasicOutputMixin, GenericBlinds):
    gateway_class = FleetGatewayHandler
    config_form = BlindsConfigForm

    def _get_occupied_pins(self):
        pins = [
            self.component.config['open_pin_no'],
            self.component.config['close_pin_no']
        ]
        for p in self.component.config.get('controls', []):
            pins.append(p['pin'])
        return pins


class TTLock(FleeDeviceMixin, Lock):
    gateway_class = FleetGatewayHandler
    config_form = TTLockConfigForm
    name = 'TTLock'
    discovery_msg = _("Please activate your TTLock so it can be discovered.")

    def _send_to_device(self, value):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            set_val=value,
            component_id=self.component.id,
        ).publish()

    @classmethod
    def init_discovery(self, form_cleaned_data):
        from simo.core.models import Gateway
        print("Serialized form: ", serialize_form_data(form_cleaned_data))
        gateway = Gateway.objects.filter(type=self.gateway_class.uid).first()
        gateway.start_discovery(
            self.uid, serialize_form_data(form_cleaned_data),
            timeout=60
        )
        GatewayObjectCommand(
            gateway, form_cleaned_data['colonel'],
            command='discover-ttlock',
        ).publish()

    @classmethod
    def _process_discovery(cls, started_with, data):
        if data['discover-ttlock'] == 'fail':
            if data['result'] == 0:
                return {'error': 'Internal Colonel error. See Colonel logs.'}
            if data['result'] == 1:
                return {'error': 'TTLock not found.'}
            elif data['result'] == 2:
                return {'error': 'Error connecting to your TTLock.'}
            elif data['result'] == 3:
                return {
                    'error': 'Unable to initialize your TTLock. '
                             'Perform full reset. '
                             'Allow the lock to rest for at least 2 min. '
                             'Move your lock as close as possible to your SIMO.io Colonel. '
                             'Retry!'
                }
            elif data['result'] == 4:
                return {
                    'error': 'BLE is available only on LAN connected colonels.'
                }
            elif data['result'] == 5:
                return {
                    'error': 'Single TTLock is alowed per Colonel.'
                }
            else:
                return {'error': data['result']}

        started_with = deserialize_form_data(started_with)
        form = TTLockConfigForm(controller_uid=cls.uid, data=started_with)
        if form.is_valid():
            new_component = form.save()
            new_component.config.update(data.get('result', {}).get('config'))
            new_component.meta['finalization_data'] = {
                'temp_id': data['result']['id'],
                'permanent_id': new_component.id,
                'config': {
                    'type': cls.uid.split('.')[-1],
                    'config': new_component.config,
                    'val': False,
                },
            }
            new_component.save()
            GatewayObjectCommand(
                new_component.gateway, Colonel(
                    id=new_component.config['colonel']
                ), command='finalize',
                data=new_component.meta['finalization_data'],
            ).publish()
            return [new_component]

        # Literally impossible, but just in case...
        return {'error': 'INVALID INITIAL DISCOVERY FORM!'}


    def add_code(self, code):
        code = str(code)
        assert 4 <= len(code) <= 8
        for no in code:
            try:
                int(no)
            except:
                raise AssertionError("Digits only please!")
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='add_code', args=[str(code)]
        ).publish()

    def delete_code(self, code):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='delete_code', args=[str(code)]
        ).publish()

    def get_codes(self):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='get_codes'
        ).publish()


    def add_fingerprint(self):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='add_fingerprint'
        ).publish()

    def delete_fingerprint(self, code):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='delete_fingerprint', args=[str(code)]
        ).publish()

    def get_fingerprints(self):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='get_fingerprints'
        ).publish()



