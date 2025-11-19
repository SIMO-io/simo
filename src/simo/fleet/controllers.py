import json, ast
from django.utils.translation import gettext_lazy as _
from django.db.transaction import atomic
from simo.core.middleware import get_current_instance
from simo.core.events import GatewayObjectCommand
from simo.core.controllers import (
    BinarySensor as BaseBinarySensor,
    Button as BaseButton,
    NumericSensor as BaseNumericSensor,
    Switch as BaseSwitch, Dimmer as BaseDimmer,
    MultiSensor as BaseMultiSensor, RGBWLight as BaseRGBWLight,
    Blinds as BaseBlinds, Gate as BaseGate,
    Lock, ControllerBase, SingleSwitchWidget
)
from simo.core.app_widgets import NumericSensorWidget, AirQualityWidget
from .base_types import DaliDeviceType, SentinelType, VoiceAssistantType
from simo.core.utils.helpers import heat_index
from simo.core.utils.serialization import (
    serialize_form_data, deserialize_form_data
)
from simo.core.forms import BaseComponentForm
from simo.generic.controllers import StateSelect
from .models import Colonel
from .gateways import FleetGatewayHandler
from .utils import get_i2c_interface_no
from .forms import (
    ColonelPinChoiceField,
    ColonelBinarySensorConfigForm, ColonelButtonConfigForm,
    ColonelSwitchConfigForm, ColonelPWMOutputConfigForm, DC10VConfigForm,
    ColonelNumericSensorConfigForm, ColonelRGBLightConfigForm,
    ColonelDHTSensorConfigForm, DS18B20SensorConfigForm,
    BME680SensorConfigForm, MCP9808SensorConfigForm, ENS160SensorConfigForm,
    DualMotorValveForm, BlindsConfigForm, GateConfigForm,
    BurglarSmokeDetectorConfigForm,
    TTLockConfigForm, DALIDeviceConfigForm, DaliLampForm, DaliGearGroupForm,
    DaliSwitchConfigForm,
    DaliOccupancySensorConfigForm, DALILightSensorConfigForm,
    DALIButtonConfigForm, SentinelDeviceConfigForm,
    RoomZonePresenceConfigForm, VoiceAssistantConfigForm
)


class FleetDeviceMixin:

    def update_options(self, options):
        """Update runtime options on the device via the Colonel gateway.

        Parameters:
        - options (dict): Device-specific options; merged on the device side.
        """
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            command='update_options',
            id=self.component.id,
            options=options
        ).publish()

    def disable_controls(self):
        """Disable device controls temporarily (e.g., lock UI inputs)."""
        options = self.component.meta.get('options', {})
        if options.get('controls_enabled', True) != False:
            options['controls_enabled'] = False
            self.update_options(options)

    def enable_controls(self):
        """Enable device controls if previously disabled."""
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

    def _call_cmd(self, method, *args, **kwargs):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id, command='call', method=method,
            args=args, kwargs=kwargs
        ).publish()


class BasicSensorMixin:
    gateway_class = FleetGatewayHandler
    accepts_value = False

    def _get_occupied_pins(self):
        return [
            self.component.config['pin_no'],
        ]

class BinarySensor(FleetDeviceMixin, BasicSensorMixin, BaseBinarySensor):
    config_form = ColonelBinarySensorConfigForm


class Button(FleetDeviceMixin, BasicSensorMixin, BaseButton):
    config_form = ColonelButtonConfigForm


class BurglarSmokeDetector(BinarySensor):
    config_form = BurglarSmokeDetectorConfigForm
    name = 'Smoke Detector (Burglar)'

    def _get_occupied_pins(self):
        return [
            self.component.config['power_pin_no'],
            self.component.config['sensor_pin_no']
        ]


class DS18B20Sensor(FleetDeviceMixin, BasicSensorMixin, BaseNumericSensor):
    config_form = DS18B20SensorConfigForm
    name = "DS18B20 Temperature sensor"


class DHTSensor(FleetDeviceMixin, BasicSensorMixin, BaseMultiSensor):
    config_form = ColonelDHTSensorConfigForm
    name = "DHT climate sensor"
    app_widget = NumericSensorWidget

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sys_temp_units = 'C'
        if hasattr(self.component, 'zone') \
                and self.component.zone.instance.units_of_measure == 'imperial':
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


class BME680Sensor(DHTSensor):
    gateway_class = FleetGatewayHandler
    config_form = BME680SensorConfigForm
    name = "BME68X Climate Sensor (I2C)"

    def _get_occupied_pins(self):
        interface_no = get_i2c_interface_no(self.component.config)
        if interface_no is None:
            return []
        return [interface_no + 100]



class MCP9808TempSensor(FleetDeviceMixin, BaseNumericSensor):
    gateway_class = FleetGatewayHandler
    config_form = MCP9808SensorConfigForm
    name = "MCP9808 Temperature Sensor (I2C)"

    @property
    def default_value_units(self):
        instance = get_current_instance()
        if not instance:
            return 'C'
        if instance.units_of_measure == 'imperial':
            return 'F'
        return 'C'

    def _get_occupied_pins(self):
        interface_no = get_i2c_interface_no(self.component.config)
        if interface_no is None:
            return []
        return [interface_no + 100]

    def _prepare_for_set(self, value):
        if self.component.zone.instance.units_of_measure == 'imperial':
            return round((value[0][1] * 9 / 5) + 32, 1)
        return value


class ENS160AirQualitySensor(FleetDeviceMixin, BaseMultiSensor):
    gateway_class = FleetGatewayHandler
    config_form = ENS160SensorConfigForm
    name = "ENS160 Air Quality Sensor (I2C)"
    app_widget = AirQualityWidget

    default_value = [
        ["CO2", 0, "ppm"],
        ["TVOC", 0, "ppb"],
        ["AQI (UBA)", 0, ""]
    ]

    def _get_occupied_pins(self):
        interface_no = get_i2c_interface_no(self.component.config)
        if interface_no is None:
            return []
        return [interface_no + 100]

    def get_co2(self):
        try:
            for entry in self.component.value:
                if entry[0] == 'CO2':
                    return entry[1]
        except:
            return

    def get_tvoc(self):
        try:
            for entry in self.component.value:
                if entry[0] == 'TVOC':
                    return entry[1]
        except:
            return

    def get_aqi(self):
        try:
            for entry in self.component.value:
                if entry[0] == 'AQI (UBA)':
                    return entry[1]
        except:
            return


class BasicOutputMixin:
    gateway_class = FleetGatewayHandler

    def _get_occupied_pins(self):
        pins = [self.component.config['output_pin_no']]
        for ctrl in self.component.config.get('controls', []):
            if 'pin_no' in ctrl:
                pins.append(ctrl['pin_no'])
        return pins

    def _ctrl(self, ctrl_no, ctrl_event, method):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id, command='call', method='ctrl',
            args=[ctrl_no, ctrl_event, method]
        ).publish()


class Switch(FleetDeviceMixin, BasicOutputMixin, BaseSwitch):
    config_form = ColonelSwitchConfigForm

    def signal(self, pulses):
        '''
        Expecting list of tuples where each item represents component value
        followed by duration in miliseconds.
        Maximum of 20 pulses is accepted, each pulse might not be longer than 3000ms
        If you need anything longer than this, use on(), off() methods instead.
        :param pulses: [(True, 200), (False, 600), (True, 200)]
        :return: None
        '''
        assert len(pulses) > 0, "At least on pulse is expected"
        assert len(pulses) <= 20, "No more than 20 pulses is accepted"
        for i, pulse in enumerate(pulses):
            assert isinstance(pulse[0], bool), f"{i+1}-th pulse is not boolean!"
            assert pulse[1] <= 3000, "Pulses must not exceed 3000ms"

        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            command='call', method='signal', args=[pulses],
            id=self.component.id,
        ).publish()


class FadeMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.component.last_fade_direction = 0

    def fade_up(self):
        self.component.last_fade_direction = 1
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id, command='call', method='fade_up'
        ).publish()

    def fade_down(self):
        self.component.last_fade_direction = -1
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id, command='call', method='fade_down'
        ).publish()

    def fade_stop(self):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id, command='call', method='fade_stop'
        ).publish()


class PWMOutput(FadeMixin, FleetDeviceMixin, BasicOutputMixin, BaseDimmer):
    name = "AC/DC Dimmer | PWM Driver"
    config_form = ColonelPWMOutputConfigForm

    def _prepare_for_send(self, value):
        conf = self.component.config
        if value >= conf.get('max', 100):
            value = conf.get('max', 100)
        elif value < conf.get('min', 0):
            value = conf.get('min', 0)

        if value >= conf.get('max', 100):
            pwm_value = 0
        elif value <= conf.get('min', 100):
            pwm_value = 1023
        else:
            val_amplitude = conf.get('max', 100) - conf.get('min', 0)
            val_relative = value / val_amplitude

            duty_max = 1023 - (conf.get('device_min', 0) * 0.01 * 1023)
            duty_min = 1023 - conf.get('device_max', 100) * 0.01 * 1023

            pwm_amplitude = duty_max - duty_min
            pwm_value = duty_min + pwm_amplitude * val_relative

            pwm_value = duty_max - pwm_value + duty_min

        return pwm_value

    def _prepare_for_set(self, pwm_value):
        conf = self.component.config
        duty_max = 1023 - conf.get('device_min', 0) * 0.01 * 1023
        duty_min = 1023 - conf.get('device_max', 100) * 0.01 * 1023

        if pwm_value > duty_max:
            value = conf.get('max', 100)
        elif pwm_value < duty_min:
            value = conf.get('min', 0)
        else:
            pwm_amplitude = duty_max - duty_min
            relative_value = (pwm_value - duty_min) / pwm_amplitude
            val_amplitude = conf.get('max', 100) - conf.get('min', 0)
            value = conf.get('min', 0) + val_amplitude * relative_value

        value = conf.get('max', 100) - value + conf.get('min', 0)

        return round(value, 3)


class DC10VDriver(FadeMixin, FleetDeviceMixin, BasicOutputMixin, BaseDimmer):
    name = "0 - 10V Driver"
    config_form = DC10VConfigForm
    default_value_units = '%'

    def _prepare_for_send(self, value):
        conf = self.component.config
        if value >= conf.get('max', 100):
            value = conf.get('max', 100)
        elif value < conf.get('min', 0):
            value = conf.get('min', 0)

        if value >= conf.get('max', 100):
            if conf.get('inverse') == True:
                pwm_value = 0
            else:
                pwm_value = 1023
        elif value <= conf.get('min', 0):
            if conf.get('inverse') == True:
                pwm_value = 1023
            else:
                pwm_value = 0
        else:
            val_amplitude = conf.get('max', 100) - conf.get('min', 0)
            val_relative = value / val_amplitude

            if conf.get('inverse') == True:
                duty_max = 1023 - conf.get('device_min', 0) / 10 * 1023
                duty_min = 1023 - conf.get('device_max', 10) / 10 * 1023
                pwm_amplitude = duty_max - duty_min
                pwm_value = duty_min + pwm_amplitude * val_relative
                pwm_value = duty_max - pwm_value + duty_min
            else:
                duty_max = conf.get('device_max', 10) / 10 * 1023
                duty_min = conf.get('device_min', 0) / 10 * 1023
                pwm_amplitude = duty_max - duty_min
                pwm_value = duty_min + pwm_amplitude * val_relative

        return pwm_value

    def _prepare_for_set(self, pwm_value):
        conf = self.component.config
        if conf.get('inverse') == True:
            pwm_value = 1023 - pwm_value
        duty_max = conf.get('device_max', 10) / 10 * 1023
        duty_min = conf.get('device_min', 0) / 10 * 1023

        if pwm_value > duty_max:
            value = conf.get('max', 100)
        elif pwm_value < duty_min:
            value = conf.get('min', 0)
        else:
            pwm_amplitude = duty_max - duty_min
            relative_value = (pwm_value - duty_min) / pwm_amplitude
            val_amplitude = conf.get('max', 100) - conf.get('min', 0)
            value = conf.get('min', 0) + val_amplitude * relative_value

        return round(value, 3)


class RGBLight(FleetDeviceMixin, BasicOutputMixin, BaseRGBWLight):
    config_form = ColonelRGBLightConfigForm


class DualMotorValve(FleetDeviceMixin, BasicOutputMixin, BaseDimmer):
    gateway_class = FleetGatewayHandler
    config_form = DualMotorValveForm
    name = "Dual Motor Valve"
    default_config = {}

    def _get_occupied_pins(self):
        return [
            self.component.config['open_pin_no'],
            self.component.config['close_pin_no']
        ]

    def _prepare_for_send(self, value):
        conf = self.component.config
        if value >= conf.get('max', 100):
            value = conf.get('max', 100)
        elif value < conf.get('min', 0):
            value = conf.get('min', 0)
        val_amplitude = conf.get('max', 100) - conf.get('min', 0)
        return ((value - conf.get('min', 0)) / val_amplitude) * 100


    def _prepare_for_set(self, value):
        conf = self.component.config
        if value > conf.get('max', 100):
            value = conf.get('max', 100)
        elif value < conf.get('min', 0.0):
            value = conf.get('min', 0)
        val_amplitude = conf.get('max', 100) - conf.get('min', 0)
        return conf.get('min', 0) + (value / 100) * val_amplitude


class Blinds(FleetDeviceMixin, BasicOutputMixin, BaseBlinds):
    gateway_class = FleetGatewayHandler
    config_form = BlindsConfigForm

    def _get_occupied_pins(self):
        pins = [
            self.component.config['open_pin_no'],
            self.component.config['close_pin_no']
        ]
        for ctrl in self.component.config.get('controls', []):
            if 'pin_no' in ctrl:
                pins.append(ctrl['pin_no'])
        return pins


class Gate(FleetDeviceMixin, BasicOutputMixin, BaseGate):
    gateway_class = FleetGatewayHandler
    config_form = GateConfigForm

    def _get_occupied_pins(self):
        pins = [
            self.component.config['control_pin_no'],
            self.component.config['sensor_pin_no']
        ]
        for ctrl in self.component.config.get('controls', []):
            if 'pin_no' in ctrl:
                pins.append(ctrl['pin_no'])
        return pins



class TTLock(FleetDeviceMixin, Lock):
    gateway_class = FleetGatewayHandler
    config_form = TTLockConfigForm
    name = 'TTLock'
    discovery_msg = _("Please activate your TTLock so it can be discovered.")

    @classmethod
    def _init_discovery(self, form_cleaned_data):
        from simo.core.models import Gateway
        print("INIT discovery form cleaned data: ", form_cleaned_data)
        print("Serialized form: ", serialize_form_data(form_cleaned_data))
        gateway = Gateway.objects.filter(type=self.gateway_class.uid).first()
        gateway.start_discovery(
            self.uid, serialize_form_data(form_cleaned_data),
            timeout=60
        )
        GatewayObjectCommand(
            gateway, form_cleaned_data['colonel'],
            command='discover', type=self.uid
        ).publish()

    @classmethod
    @atomic
    def _process_discovery(cls, started_with, data):
        if data['discovery-result'] == 'fail':
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
            new_component.gateway.finish_discovery()
            colonel = Colonel.objects.get(id=new_component.config['colonel'])
            colonel.update_config()
            return [new_component]

        # Literally impossible, but just in case...
        return {'error': 'INVALID INITIAL DISCOVERY FORM!'}


    def add_code(self, code):
        """Add a numeric access code to the smart lock.

        Parameters:
        - code (str|int): 4–8 digit numeric code.
        """
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
        """Delete a numeric access code from the lock.

        Parameters:
        - code (str|int): The exact code to remove.
        """
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='delete_code', args=[str(code)]
        ).publish()

    def clear_codes(self):
        """Remove all numeric access codes from the lock."""
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='clear_codes'
        ).publish()

    def get_codes(self):
        """Request the list of numeric access codes from the lock."""
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='get_codes'
        ).publish()

    def add_fingerprint(self):
        """Start lock-side enrollment of a new fingerprint."""
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='add_fingerprint'
        ).publish()

    def delete_fingerprint(self, code):
        """Delete a fingerprint by its identifier on the lock."""
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='delete_fingerprint', args=[str(code)]
        ).publish()

    def clear_fingerprints(self):
        """Remove all fingerprints from the lock."""
        self.component.meta['clear_fingerprints'] = True
        self.component.save(update_fields=['meta'])
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='clear_fingerprints'
        ).publish()

    def get_fingerprints(self):
        """Request the list of fingerprint identifiers from the lock."""
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='get_fingerprints'
        ).publish()

    def check_locked_status(self):
        """Force an immediate connection to the lock to refresh status.

        The lock usually reports status periodically to save batteries; this
        method asks the gateway to connect proactively so that an update is
        expected within a couple of seconds.
        """
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='check_locked_status'
        ).publish()

    def _receive_meta(self, data):
        from simo.users.models import Fingerprint
        if 'codes' in data:
            self.component.meta['codes'] = data['codes']
            for code in data['codes']:
                Fingerprint.objects.get_or_create(
                    value=f"ttlock-{self.component.id}-code-{str(code)}",
                    defaults={'type': "TTLock code"}
                )
        if 'fingerprints' in data:
            self.component.meta['fingerprints'] = data['fingerprints']
            for finger in data['fingerprints']:
                Fingerprint.objects.get_or_create(
                    value=f"ttlock-{self.component.id}-finger-{str(finger)}",
                    defaults={'type': "TTLock code"}
                )
        self.component.save(update_fields=['meta'])



class DALIDevice(FleetDeviceMixin, ControllerBase):
    gateway_class = FleetGatewayHandler
    config_form = DALIDeviceConfigForm
    name = "DALI Device"
    discovery_msg = _("Please hook up your new DALI device to your DALI bus.")

    base_type = DaliDeviceType
    default_value = False
    app_widget = SingleSwitchWidget

    def _validate_val(self, value, occasion=None):
        return value

    def send(self, value):
        """Control DALI device on/off.

        Parameters:
        - value (bool): True to turn on; False to turn off.
        """
        return super().send(value)

    @classmethod
    def _init_discovery(self, form_cleaned_data):
        from simo.core.models import Gateway
        gateway = Gateway.objects.filter(type=self.gateway_class.uid).first()
        gateway.start_discovery(
            self.uid, serialize_form_data(form_cleaned_data),
            timeout=60
        )
        GatewayObjectCommand(
            gateway, form_cleaned_data['colonel'],
            command='discover', type=self.uid,
            i=form_cleaned_data['interface'].no
        ).publish()

    @classmethod
    @atomic
    def _process_discovery(cls, started_with, data):
        if data['discovery-result'] == 'fail':
            if data['result'] == 1:
                return {'error': 'DALI interface is unavailable!'}
            elif data['result'] == 2:
                return {'error': 'No new DALI devices were found!'}
            elif data['result'] == 2:
                return {'error': 'DALI line is fully occupied, no more devices can be included!'}
            else:
                return {'error': 'Unknown error!'}

        from simo.core.models import Component
        from simo.core.utils.type_constants import CONTROLLER_TYPES_MAP
        controller_uid = 'simo.fleet.controllers.' + data['result']['type']
        if controller_uid not in CONTROLLER_TYPES_MAP:
            return {'error': f"Unknown controller type: {controller_uid}"}

        comp = Component.objects.filter(
            controller_uid=controller_uid,
            meta__finalization_data__temp_id=data['result']['id']
        ).first()
        if comp:
            print(f"{comp} is already created.")
            GatewayObjectCommand(
                comp.gateway, Colonel(
                    id=comp.config['colonel']
                ), command='finalize',
                data=comp.meta['finalization_data']
            ).publish()
            return [comp]

        controller_cls = CONTROLLER_TYPES_MAP[controller_uid]

        started_with = deserialize_form_data(started_with)
        started_with['name'] += f" {data['result']['config']['da']}"
        if data['result'].get('di') is not None:
            started_with['name'] += f" - {data['result']['di']}"
        started_with['controller_uid'] = controller_uid
        # Normalize base type to slug for form
        bt = getattr(controller_cls, 'base_type', None)
        started_with['base_type'] = bt if isinstance(bt, str) else getattr(bt, 'slug', None)
        form = controller_cls.config_form(
            controller_uid=controller_cls.uid, data=started_with
        )

        if form.is_valid():
            new_component = form.save()
            new_component = Component.objects.get(id=new_component.id)
            new_component.config.update(data.get('result', {}).get('config'))

            # saving it to meta, for repeated delivery
            new_component.meta['finalization_data'] = {
                'temp_id': data['result']['id'],
                'permanent_id': new_component.id,
                'comp_config': {
                    'type': controller_uid.split('.')[-1],
                    'family': new_component.controller.family,
                    'config': json.loads(json.dumps(new_component.config))
                }
            }
            new_component.save()
            GatewayObjectCommand(
                new_component.gateway, Colonel(
                    id=new_component.config['colonel']
                ), command='finalize',
                data=new_component.meta['finalization_data']
            ).publish()
            return [new_component]

        # Literally impossible, but just in case...
        return {'error': 'INVALID INITIAL DISCOVERY FORM!'}

    def replace(self):
        """Replace a failed DALI device with a brand new one on the line.

        Connect a new device to the DALI bus and invoke this method on the
        existing (dead) component to transfer configuration to the newcomer.
        """
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id, command='call', method='replace'
        ).publish()


class DALILamp(FadeMixin, BaseDimmer, DALIDevice):
    family = 'dali'
    manual_add = False
    name = 'DALI Lamp'
    config_form = DaliLampForm


class DALIGearGroup(FadeMixin, FleetDeviceMixin, BaseDimmer):
    gateway_class = FleetGatewayHandler
    family = 'dali'
    manual_add = True
    name = 'DALI Gear Group'
    config_form = DaliGearGroupForm

    def _modify_member_group(self, member, group, remove=False):
        groups = set(member.config.get('groups', []))
        if remove:
            if group in groups:
                groups.remove(group)
        else:
            if group not in groups:
                groups.add(group)
        member.config['groups'] = list(groups)
        member.save()
        colonel = Colonel.objects.filter(
            id=member.config.get('colonel', 0)
        ).first()
        if not colonel:
            return
        GatewayObjectCommand(
            member.gateway, colonel, id=member.id,
            command='call', method='update_config',
            args=[member.controller._get_colonel_config()]
        ).publish()


class DALIRelay(BaseSwitch, DALIDevice):
    '''Not tested with a real device yet'''
    family = 'dali'
    manual_add = False
    name = 'DALI Relay'
    config_form = DaliSwitchConfigForm


class DALIOccupancySensor(BaseBinarySensor, DALIDevice):
    family = 'dali'
    manual_add = False
    name = 'DALI Occupancy Sensor'
    config_form = DaliOccupancySensorConfigForm


class DALILightSensor(BaseNumericSensor, DALIDevice):
    family = 'dali'
    manual_add = False
    name = 'DALI Light Sensor'
    default_value_units = 'lux'
    config_form = DALILightSensorConfigForm


class DALIButton(BaseButton, DALIDevice):
    family = 'dali'
    manual_add = False
    name = 'DALI Button'
    config_form = DALIButtonConfigForm
    accepts_value = False


class Sentinel(FleetDeviceMixin, ControllerBase):
    gateway_class = FleetGatewayHandler
    config_form = SentinelDeviceConfigForm
    name = "Sentinel"
    base_type = SentinelType
    default_value = 0
    app_widget = NumericSensorWidget

    def _validate_val(self, value, occasion=None):
        return value
    
    
class RoomSiren(FleetDeviceMixin, StateSelect):
    gateway_class = FleetGatewayHandler
    config_form = BaseComponentForm
    default_config = {'states': [
        {'icon': 'bell', 'slug': 'silent', 'name': "Silent"},
        {'icon': 'bell-exclamation', 'slug': 'warning', 'name': "Warning"},
        {'icon': 'bell-on', 'slug': 'alarm', 'name': "Alarm"},
        {'icon': 'circle-check', 'slug': 'success', 'name': "Success"},
        {'icon': 'circle-xmark', 'slug': 'error', 'name': "Error"},
        {'icon': 'siren-on', 'slug': 'panic', 'name': "Panic"},
    ]}
    VALUES_MAP = {
        'silent': 0, 'warning': 1, 'alarm': 2,
        'success': 3, 'error': 4, 'panic': 5
    }

    def turn_on(self):
        self.send('panic')

    def turn_off(self):
        self.send('silent')

    def _send_to_device(self, value):
        GatewayObjectCommand(
            self.component.gateway, self.component, set_val=value
        ).publish()


class AirQualitySensor(FleetDeviceMixin, BaseMultiSensor):
    gateway_class = FleetGatewayHandler
    config_form = BaseComponentForm
    name = "Air Quality Sensor"
    app_widget = AirQualityWidget
    manual_add = False
    accepts_value = False

    default_value = [
        ["TVOC", 0, "ppb"],
        ["AQI (UBA)", 0, ""]
    ]

    def _receive_from_device(self, value, *args, **kwargs):
        aqi = 5
        if value < 2000:
            aqi = 4
        if value < 800:
            aqi = 3
        if value < 400:
            aqi = 2
        if value < 200:
            aqi = 1
        value = [
            ["TVOC", value, "ppb"],
            ["AQI (UBA)", aqi, ""]
        ]
        return super()._receive_from_device(value, *args, **kwargs)

    def get_tvoc(self):
        try:
            for entry in self.component.value:
                if entry[0] == 'TVOC':
                    return entry[1]
        except:
            return

    def get_aqi(self):
        try:
            for entry in self.component.value:
                if entry[0] == 'AQI (UBA)':
                    return entry[1]
        except:
            return


class TempHumSensor(FleetDeviceMixin, BasicSensorMixin, BaseMultiSensor):
    gateway_class = FleetGatewayHandler
    config_form = BaseComponentForm
    name = "Temperature & Humidity sensor"
    app_widget = NumericSensorWidget
    manual_add = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sys_temp_units = 'C'
        if hasattr(self.component, 'zone') \
                and self.component.zone.instance.units_of_measure == 'imperial':
            self.sys_temp_units = 'F'

    @property
    def default_value(self):
        return [
            ['temperature', 0, self.sys_temp_units],
            ['humidity', 20, '%'],
            ['real_feel', 0, self.sys_temp_units],
            ['temp_raw', 0, 'C'],
            ['hum_raw', 0, '%'],
            ['core', 0, 'C'],
            ['outside', 0, 'C']
        ]

    def _receive_from_device(self, value, *args, **kwargs):

        if isinstance(value, dict):
            temp = value['temp']
            humidity = value['hum']
        else:
            buf = bytes.fromhex(value)
            humidity = (
                (buf[0] << 12) | (buf[1] << 4) | (buf[2] >> 4)
            )
            humidity = (humidity * 100) / 0x100000
            humidity = int(round(humidity, 0))
            temp = ((buf[2] & 0xF) << 16) | (buf[3] << 8) | buf[4]
            temp = ((temp * 200.0) / 0x100000) - 50
            temp = round(temp, 1)

        new_val = [
            ['temperature', temp, self.sys_temp_units],
            ['humidity', humidity, '%'],
            ['real_feel', 0, self.sys_temp_units],
            ['temp_raw', value.get('temp_raw'), 'C'],
            ['hum_raw', value.get('hum_raw'), '%'],
            ['core', value.get('core'), 'C'],
            ['outside', value.get('out'), 'C']
        ]

        if self.sys_temp_units == 'F':
            new_val[0][1] = round((new_val[0][1] * 9 / 5) + 32, 1)

        real_feel = heat_index(
            new_val[0][1], new_val[1][1], self.sys_temp_units == 'F'
        )
        new_val[2] = ['real_feel', real_feel, self.sys_temp_units]

        return super()._receive_from_device(new_val, *args, **kwargs)


class AmbientLightSensor(FleetDeviceMixin, BaseNumericSensor):
    gateway_class = FleetGatewayHandler
    name = "Ambient lighting sensor"
    manual_add = False
    default_value_units = 'lux'
    default_config = {
        'widget': 'numeric-sensor',
        'value_units': 'lux',
        'limits': [
            {"name": "Dark", "value": 20},
            {"name": "Moderate", "value": 300},
            {"name": "Bright", "value": 800},
        ]
    }



class RoomPresenceSensor(FleetDeviceMixin, BaseBinarySensor):
    gateway_class = FleetGatewayHandler
    name = "Human presence sensor"
    manual_add = False


class RoomZonePresenceSensor(FleetDeviceMixin, BaseBinarySensor):
    gateway_class = FleetGatewayHandler
    add_form = RoomZonePresenceConfigForm
    config_form = BaseComponentForm
    name = "Room zone presence"
    discovery_msg = _(
        "Your body is a a live space marker now! Your movements are being recorded.<br>"
        "Whenever you hear a beep, new space blob is being included.<br>"
        "Move vigorously in the zone where you want presence to be detected until "
        "you hear no more beeps.<br> "
        "Green color of a sensor indicates, "
        "that the space you are currently in is "
        "already included.<br>"
        "Tip: Dance! :)"
    )

    @classmethod
    def _init_discovery(self, form_cleaned_data):
        from simo.core.models import Gateway
        gateway = Gateway.objects.filter(type=self.gateway_class.uid).first()
        gateway.start_discovery(
            self.uid, serialize_form_data(form_cleaned_data),
            timeout=60
        )
        colonel = Colonel.objects.filter(
            id=form_cleaned_data.get('colonel')
            if isinstance(form_cleaned_data.get('colonel'), int)
            else getattr(form_cleaned_data.get('colonel'), 'id', None)
        ).first()
        if colonel:
            GatewayObjectCommand(
                gateway, colonel,
                command='discover', type=self.uid.split('.')[-1],
            ).publish()


    @classmethod
    @atomic
    def _finish_discovery(cls, started_with):
        started_with = deserialize_form_data(started_with)
        form = cls.add_form(
            controller_uid=cls.uid, data=started_with
        )
        from simo.core.middleware import introduce_instance
        introduce_instance(form.data['zone'].instance)
        form = cls.add_form(
            controller_uid=cls.uid, data=started_with
        )
        form.is_valid()
        form.instance.alive = False
        form.instance.config['colonel'] = int(
            getattr(form.cleaned_data['colonel'], 'id', form.cleaned_data['colonel'])
        )
        new_component = form.save()
        GatewayObjectCommand(
            new_component.gateway, Colonel(
                id=new_component.config['colonel']
            ), command='finalize',
            data={
                'permanent_id': new_component.id,
                'comp_config': {
                    'type': cls.uid.split('.')[-1],
                    'family': new_component.controller.family,
                    'config': json.loads(json.dumps(new_component.config)),
                }
            }
        ).publish()

        return new_component

    def repaint(self):
        """Repaint included 3D space"""
        GatewayObjectCommand(
            self.component.gateway, Colonel(
                id=self.component.config['colonel']
            ), command='call', method='repaint', id=self.component.id
        ).publish()

    def finish_repaint(self):
        """Finish repainting of 3D space"""
        GatewayObjectCommand(
            self.component.gateway, Colonel(
                id=self.component.config['colonel']
            ), command='call', method='finish_repaint',
            id=self.component.id
        ).publish()

    def cancel_repaint(self):
        """Finish repainting of 3D space"""
        GatewayObjectCommand(
            self.component.gateway, Colonel(
                id=self.component.config['colonel']
            ), command='call', method='cancel_repaint',
            id=self.component.id
        ).publish()


class SmokeDetector(FleetDeviceMixin, BaseBinarySensor):
    name = _("Dust/pollution detector")
    gateway_class = FleetGatewayHandler
    manual_add = False


class VoiceAssistant(FleetDeviceMixin, BaseBinarySensor):
    base_type = VoiceAssistantType
    name = _("AI Voice Assistant")
    gateway_class = FleetGatewayHandler
    config_form = VoiceAssistantConfigForm
    manual_add = False
    default_config = {'voice': 'male', 'enabled': True}

    def arm(self):
        """
            Arming voice assistant is means disabling it,
            so that it can not be used by invaders.
        """
        self.component.refresh_from_db()
        self.component.config['enabled'] = False
        self.component.arm_status = 'armed'
        self.component.save()
        GatewayObjectCommand(
            self.component.gateway, Colonel(
                id=self.component.config['colonel']
            ), command='call', method='disable',
            id=self.component.id
        ).publish()

    def disarm(self):
        """
            Disarming voice assistant is means enabling it,
            so that anyone can use it to control the smart home system.
        """
        self.component.refresh_from_db()
        self.component.config['enabled'] = True
        self.component.arm_status = 'disarmed'
        self.component.save()
        GatewayObjectCommand(
            self.component.gateway, Colonel(
                id=self.component.config['colonel']
            ), command='call', method='enable',
            id=self.component.id
        ).publish()

    def is_in_alarm(self):
        """Returns always False"""
        return False
