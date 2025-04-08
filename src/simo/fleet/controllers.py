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
)
from simo.core.app_widgets import NumericSensorWidget, AirQualityWidget
from simo.core.controllers import Lock, ControllerBase, SingleSwitchWidget
from simo.core.utils.helpers import heat_index
from simo.core.utils.serialization import (
    serialize_form_data, deserialize_form_data
)
from simo.core.forms import BaseComponentForm
from .models import Colonel, CustomDaliDevice
from .gateways import FleetGatewayHandler
from .forms import (
    ColonelPinChoiceField,
    ColonelBinarySensorConfigForm, ColonelButtonConfigForm,
    ColonelSwitchConfigForm, ColonelPWMOutputConfigForm, DCDriverConfigForm,
    ColonelNumericSensorConfigForm, ColonelRGBLightConfigForm,
    ColonelDHTSensorConfigForm, DS18B20SensorConfigForm,
    BME680SensorConfigForm, MCP9808SensorConfigForm, ENS160SensorConfigForm,
    DualMotorValveForm, BlindsConfigForm, GateConfigForm,
    BurglarSmokeDetectorConfigForm,
    TTLockConfigForm, DALIDeviceConfigForm, DaliLampForm, DaliGearGroupForm,
    DaliSwitchConfigForm,
    DaliOccupancySensorConfigForm, DALILightSensorConfigForm,
    DALIButtonConfigForm, RoomSensorDeviceConfigForm,
    RoomZonePresenceConfigForm
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

    def _call_cmd(self, method, *args, **kwargs):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id, command='call', method=method,
            args=args, kwargs=kwargs
        ).publish()


class BasicSensorMixin:
    gateway_class = FleetGatewayHandler

    def _get_occupied_pins(self):
        return [
            self.component.config['pin_no'],
        ]

class BinarySensor(FleeDeviceMixin, BasicSensorMixin, BaseBinarySensor):
    config_form = ColonelBinarySensorConfigForm


class Button(FleeDeviceMixin, BasicSensorMixin, BaseButton):
    config_form = ColonelButtonConfigForm


class BurglarSmokeDetector(BinarySensor):
    config_form = BurglarSmokeDetectorConfigForm
    name = 'Smoke Detector (Burglar)'

    def _get_occupied_pins(self):
        return [
            self.component.config['power_pin_no'],
            self.component.config['sensor_pin_no']
        ]


class DS18B20Sensor(FleeDeviceMixin, BasicSensorMixin, BaseNumericSensor):
    config_form = DS18B20SensorConfigForm
    name = "DS18B20 Temperature sensor"


class DHTSensor(FleeDeviceMixin, BasicSensorMixin, BaseMultiSensor):
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



class MCP9808TempSensor(FleeDeviceMixin, BaseNumericSensor):
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

    def _prepare_for_set(self, value):
        if self.component.zone.instance.units_of_measure == 'imperial':
            return round((value[0][1] * 9 / 5) + 32, 1)
        return value


class ENS160AirQualitySensor(FleeDeviceMixin, BaseMultiSensor):
    gateway_class = FleetGatewayHandler
    config_form = ENS160SensorConfigForm
    name = "ENS160 Air Quality Sensor (I2C)"
    app_widget = AirQualityWidget

    default_value = [
        ["CO2", 0, "ppm"],
        ["TVOC", 0, "ppb"],
        ["AQI (UBA)", 0, ""]
    ]

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


class Switch(FleeDeviceMixin, BasicOutputMixin, BaseSwitch):
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


class PWMOutput(FadeMixin, FleeDeviceMixin, BasicOutputMixin, BaseDimmer):
    name = "Dimmer"
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
        duty_max = 1023 - (conf.get('device_min', 0) * 0.01 * 1023)
        duty_min = 1023 - conf.get('device_max', 100) * 0.01 * 1023

        if pwm_value > duty_max:
            value = conf.get('max', 100)
        elif pwm_value < duty_min:
            value = conf.get('min', 0)
        else:
            pwm_amplitude =duty_max - duty_min
            relative_value = (pwm_value - duty_min) / pwm_amplitude
            val_amplitude = conf.get('max', 100) - conf.get('min', 0)
            value = conf.get('min', 0) + val_amplitude * relative_value

        value = conf.get('max', 100) - value + conf.get('min', 0)

        return round(value, 3)


class DCDriver(FadeMixin, FleeDeviceMixin, BasicOutputMixin, BaseDimmer):
    name = "0 - 24V DC Driver"
    config_form = DCDriverConfigForm
    default_value_units = 'V'

    def _prepare_for_send(self, value):
        conf = self.component.config
        if value >= conf.get('max', 24):
            value = conf.get('max', 24)
        elif value < conf.get('min', 0):
            value = conf.get('min', 0)

        if value >= conf.get('max', 24):
            pwm_value = 1023
        elif value <= conf.get('min', 100):
            pwm_value = 0
        else:
            val_amplitude = conf.get('max', 24) - conf.get('min', 0)
            val_relative = value / val_amplitude

            duty_max = conf.get('device_max', 24) / 24 * 1023
            duty_min = conf.get('device_min', 0) / 24 * 1023

            pwm_amplitude = duty_max - duty_min
            pwm_value = duty_min + pwm_amplitude * val_relative

        return pwm_value

    def _prepare_for_set(self, pwm_value):
        conf = self.component.config
        duty_max = conf.get('device_max', 24) / 24 * 1023
        duty_min = conf.get('device_min', 0) / 24 * 1023

        if pwm_value > duty_max:
            value = conf.get('max', 24)
        elif pwm_value < duty_min:
            value = conf.get('min', 0)
        else:
            pwm_amplitude = duty_max - duty_min
            relative_value = (pwm_value - duty_min) / pwm_amplitude
            val_amplitude = conf.get('max', 24) - conf.get('min', 0)
            value = conf.get('min', 0) + val_amplitude * relative_value

        return round(value, 3)


class RGBLight(FleeDeviceMixin, BasicOutputMixin, BaseRGBWLight):
    config_form = ColonelRGBLightConfigForm


class DualMotorValve(FleeDeviceMixin, BasicOutputMixin, BaseDimmer):
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


class Blinds(FleeDeviceMixin, BasicOutputMixin, BaseBlinds):
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


class Gate(FleeDeviceMixin, BasicOutputMixin, BaseGate):
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



class TTLock(FleeDeviceMixin, Lock):
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

    def clear_codes(self):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='clear_codes'
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

    def clear_fingerprints(self):
        self.component.meta['clear_fingerprints'] = True
        self.component.save(update_fields=['meta'])
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='clear_fingerprints'
        ).publish()

    def get_fingerprints(self):
        GatewayObjectCommand(
            self.component.gateway,
            Colonel(id=self.component.config['colonel']),
            id=self.component.id,
            command='call', method='get_fingerprints'
        ).publish()

    def check_locked_status(self):
        '''
        Lock state is monitored by capturing adv data
        periodically transmitted by the lock.
        This data includes information about it's lock/unlock position
        also if there are any new events in it that we are not yet aware of.

        If anything new is observer, connection is made to the lock
        and reported back to the system.
        This helps to save batteries of a lock,
        however it is not always as timed as we would want to.
        Sometimes it can take even up to 20s for these updates to occur.

        This method is here to force immediate connection to the lock
        to check it's current status. After this method is called,
        we might expect to receive an update within 2 seconds or less.
        '''
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



class DALIDevice(FleeDeviceMixin, ControllerBase):
    gateway_class = FleetGatewayHandler
    config_form = DALIDeviceConfigForm
    name = "DALI Device"
    discovery_msg = _("Please hook up your new DALI device to your DALI bus.")

    base_type = 'dali'
    default_value = False
    app_widget = SingleSwitchWidget

    def _validate_val(self, value, occasion=None):
        return value

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
        started_with['base_type'] = controller_cls.base_type
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
        """
        Hook up brand new replacement device to the dali line
        and execute this command on existing (dead) component instance,
        so that it can be replaced by the new physical device.
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


class DALIGearGroup(FadeMixin, FleeDeviceMixin, BaseDimmer):
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


class RoomSensor(FleeDeviceMixin, ControllerBase):
    gateway_class = FleetGatewayHandler
    config_form = RoomSensorDeviceConfigForm
    name = "Room Sensor"
    base_type = 'room-sensor'
    default_value = 0
    app_widget = NumericSensorWidget

    def _validate_val(self, value, occasion=None):
        return value


class AirQualitySensor(FleeDeviceMixin, BaseMultiSensor):
    gateway_class = FleetGatewayHandler
    config_form = BaseComponentForm
    name = "Air Quality Sensor"
    app_widget = AirQualityWidget
    manual_add = False

    default_value = [
        ["TVOC", 0, "ppb"],
        ["AQI (UBA)", 0, ""]
    ]

    def _receive_from_device(self, value, *args, **kwargs):
        aqi = 5
        if value < 812:
            aqi = 4
        if value < 325:
            aqi = 3
        if value < 162:
            aqi = 2
        if value < 65:
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


class TempHumSensor(FleeDeviceMixin, BasicSensorMixin, BaseMultiSensor):
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
            ['real_feel', 0, self.sys_temp_units]
        ]

    def _receive_from_device(self, value, *args, **kwargs):

        if isinstance(value, dict):
            temp = value['temp']
            humidity = value['humidity']
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
            ['real_feel', 0, self.sys_temp_units]
        ]

        if self.sys_temp_units == 'F':
            new_val[0][1] = round((new_val[0][1] * 9 / 5) + 32, 1)

        real_feel = heat_index(
            new_val[0][1], new_val[1][1], self.sys_temp_units == 'F'
        )
        new_val[2] = ['real_feel', real_feel, self.sys_temp_units]

        return super()._receive_from_device(new_val, *args, **kwargs)


class AmbientLightSensor(FleeDeviceMixin, BaseNumericSensor):
    gateway_class = FleetGatewayHandler
    name = "Ambient lighting sensor"
    manual_add = False
    default_config = {
        'widget': 'numeric-sensor',
        'value_units': 'lux',
        'limits': [
            {"name": "Dark", "value": 20},
            {"name": "Moderate", "value": 300},
            {"name": "Bright", "value": 800},
        ]
    }


class RoomPresenceSensor(FleeDeviceMixin, BaseBinarySensor):
    gateway_class = FleetGatewayHandler
    name = "Human presence sensor"
    manual_add = False


class RoomZonePresenceSensor(FleeDeviceMixin, BaseBinarySensor):
    gateway_class = FleetGatewayHandler
    add_form = RoomZonePresenceConfigForm
    config_form = BaseComponentForm
    name = "Room zone presence"
    discovery_msg = _(
        "Move vigorously in particular zone of the room, "
        "where presence needs to be detected. "
        "Your movements are being recorded. "
        "Hit Done, once you are done."
    )

    @classmethod
    def _init_discovery(self, form_cleaned_data):
        from simo.core.models import Gateway
        gateway = Gateway.objects.filter(type=self.gateway_class.uid).first()
        gateway.start_discovery(
            self.uid, serialize_form_data(form_cleaned_data),
            timeout=60
        )
        if form_cleaned_data['device'].startswith('wifi'):
            colonel = Colonel.objects.filter(
                id=form_cleaned_data['device'][5:]
            ).first()
            GatewayObjectCommand(
                gateway, colonel,
                command='discover', type=self.uid.split('.')[-1],
            ).publish()
        else:
            dali_device = CustomDaliDevice.objects.filter(
                id=form_cleaned_data['device'][5:]
            ).first()
            from .custom_dali_operations import Frame
            frame = Frame(40, bytes(bytearray(5)))
            frame[8:11] = 15 # command to custom dali device
            frame[12:15] = 0 # action to perform: start room zone discovery
            dali_device.transmit(frame)


    @classmethod
    @atomic
    def _finish_discovery(cls, started_with):
        started_with = deserialize_form_data(started_with)
        form = cls.add_form(
            controller_uid=cls.uid, data=started_with
        )
        form.is_valid()
        if form.cleaned_data['device'].startswith('wifi'):
            form.instance.alive = False
            form.instance.config['colonel'] = int(
                form.cleaned_data['device'][5:]
            )
            new_component = form.save()
            GatewayObjectCommand(
                new_component.gateway, Colonel(
                    id=new_component.config['colonel']
                ), command='finalize',
                data={
                    'comp_config': {
                        'type': str(cls).split('.')[-1],
                        'family': new_component.controller.family,
                        'config': json.loads(json.dumps(new_component.config))
                    }
                }
            ).publish()
        else:
            from simo.core.models import Component
            dali_device = CustomDaliDevice.objects.filter(
                id=form.cleaned_data['device'][5:]
            ).first()
            free_slots = {0, 1, 2, 3, 4, 5, 6, 7}
            for comp in Component.objects.filter(
                controller_uid=cls.uid, config__dali_device=dali_device.id
            ):
                try:
                    free_slots.remove(int(comp.config['slot']))
                except:
                    continue
            if not free_slots:
                return []

            form.instance.alive = False
            form.instance.config['dali_device'] = int(
                form.cleaned_data['device'][5:]
            )
            form.instance.config['slot'] = free_slots.pop()
            new_component = form.save()
            from .custom_dali_operations import Frame
            frame = Frame(40, bytes(bytearray(5)))
            frame[8:11] = 15  # command to custom dali device
            frame[12:15] = 1  # action to perform: stop room zone discovery
            frame[16:18] = new_component.config['slot']
            dali_device.transmit(frame)

        print("NEW COMPONENT: ", new_component)
        return new_component