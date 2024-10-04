import json
from django.utils.translation import gettext_lazy as _
from django.db.transaction import atomic
from simo.core.middleware import get_current_instance
from simo.core.events import GatewayObjectCommand
from simo.core.controllers import (
    BinarySensor as BaseBinarySensor,
    Button as BaseButton,
    NumericSensor as BaseNumericSensor,
    Switch as BaseSwitch, Dimmer as BaseDimmer,
    MultiSensor as BaseMultiSensor, RGBWLight as BaseRGBWLight
)
from simo.conf import dynamic_settings
from simo.core.app_widgets import NumericSensorWidget
from simo.core.controllers import Lock, ControllerBase, SingleSwitchWidget
from simo.core.utils.helpers import heat_index
from simo.core.utils.serialization import (
    serialize_form_data, deserialize_form_data
)
from simo.generic.controllers import Blinds as GenericBlinds
from .models import Colonel, ColonelPin
from .gateways import FleetGatewayHandler
from .forms import (
    ColonelPinChoiceField,
    ColonelBinarySensorConfigForm, ColonelButtonConfigForm,
    ColonelSwitchConfigForm, ColonelPWMOutputConfigForm,
    ColonelNumericSensorConfigForm, ColonelRGBLightConfigForm,
    ColonelDHTSensorConfigForm, DS18B20SensorConfigForm,
    BME680SensorConfigForm, MPC9808SensorConfigForm, ENS160SensorConfigForm,
    DualMotorValveForm, BlindsConfigForm, BurglarSmokeDetectorConfigForm,
    TTLockConfigForm, DALIDeviceConfigForm, DaliLampForm, DaliGearGroupForm,
    DaliSwitchConfigForm,
    DaliOccupancySensorConfigForm, DALILightSensorConfigForm,
    DALIButtonConfigForm
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

    def _fix_pin_relations(self):
        pass


class BasicSensorMixin:
    gateway_class = FleetGatewayHandler

    def _get_occupied_pins(self):
        return [
            self.component.config['pin_no'],
        ]

    @atomic
    def _fix_pin_relations(self):
        colonel = Colonel.objects.filter(
            id=self.component.config.get('colonel', 0)
        ).first()
        if not colonel:
            return
        cp = ColonelPin.objects.filter(
            colonel=colonel, no=self.component.config['pin_no']
        ).first()
        if self.component.config.get('pin') != cp.id:
            self.component.config['pin'] = cp.id
            self.component.save()


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

    @atomic
    def _fix_pin_relations(self):
        colonel = Colonel.objects.filter(
            id=self.component.config.get('colonel', 0)
        ).first()
        if not colonel:
            return
        cp = ColonelPin.objects.filter(
            colonel=colonel, no=self.component.config['power_pin_no']
        ).first()
        if self.component.config.get('power_pin') != cp.id:
            self.component.config['power_pin'] = cp.id
            self.component.save()
        cp = ColonelPin.objects.filter(
            colonel=colonel, no=self.component.config['sensor_pin_no']
        ).first()
        if self.component.config.get('sensor_pin') != cp.id:
            self.component.config['sensor_pin'] = cp.id
            self.component.save()


# class AnalogSensor(FleeDeviceMixin, BasicSensorMixin, BaseNumericSensor):
#     config_form = ColonelNumericSensorConfigForm
#     name = "Analog sensor"
#
#     def _get_occupied_pins(self):
#         return [
#             self.component.config['pin_no'],
#         ]


class DS18B20Sensor(FleeDeviceMixin, BasicSensorMixin, BaseNumericSensor):
    config_form = DS18B20SensorConfigForm
    name = "DS18B20 Temperature sensor"



# TODO: need to change this to {
#                 'temp': self.sensor.temperature, 'hum': self.sensor.humidity,
#                 'pressure': self.sensor.pressure, 'gas': self.sensor.gas
#             }
# which is used by BME680Sensor

class BaseClimateSensor(FleeDeviceMixin, BasicSensorMixin, BaseMultiSensor):
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




class DHTSensor(BaseClimateSensor):
    config_form = ColonelDHTSensorConfigForm
    name = "DHT climate sensor"


class BME680Sensor(FleeDeviceMixin, BaseMultiSensor):
    gateway_class = FleetGatewayHandler
    config_form = BME680SensorConfigForm
    name = "BME680 Climate Sensor (I2C)"


class MPC9808TempSensor(FleeDeviceMixin, BaseNumericSensor):
    gateway_class = FleetGatewayHandler
    config_form = MPC9808SensorConfigForm
    name = "MPC9808 Temperature Sensor (I2C)"

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

    @atomic
    def _fix_pin_relations(self):
        colonel = Colonel.objects.filter(
            id=self.component.config.get('colonel', 0)
        ).first()
        if not colonel:
            return
        cp = ColonelPin.objects.filter(
            colonel=colonel, no=self.component.config['output_pin_no']
        ).first()
        if self.component.config.get('output_pin') != cp.id:
            self.component.config['output_pin'] = cp.id

        for ctrl in self.component.config.get('controls', []):
            if 'pin_no' not in ctrl:
                continue
            if not ctrl.get('input').startswith('pin-'):
                continue
            cp = ColonelPin.objects.filter(
                colonel=colonel, no=ctrl['pin_no']
            ).first()
            if not cp:
                continue
            ctrl['input'] = f'pin-{cp.id}'

        self.component.save()


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
            if conf.get('inverse'):
                pwm_value = 0
            else:
                pwm_value = 1023
        elif value <= conf.get('min', 100):
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

    @atomic
    def _fix_pin_relations(self):
        colonel = Colonel.objects.filter(
            id=self.component.config.get('colonel', 0)
        ).first()
        if not colonel:
            return
        cp = ColonelPin.objects.filter(
            colonel=colonel, no=self.component.config['open_pin_no']
        ).first()
        if self.component.config.get('open_pin') != cp.id:
            self.component.config['open_pin'] = cp.id
        cp = ColonelPin.objects.filter(
            colonel=colonel, no=self.component.config['close_pin_no']
        ).first()
        if self.component.config.get('close_pin') != cp.id:
            self.component.config['close_pin'] = cp.id

        self.component.save()


class Blinds(FleeDeviceMixin, BasicOutputMixin, GenericBlinds):
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

    @atomic
    def _fix_pin_relations(self):
        colonel = Colonel.objects.filter(
            id=self.component.config.get('colonel', 0)
        ).first()
        if not colonel:
            return
        cp = ColonelPin.objects.filter(
            colonel=colonel, no=self.component.config['open_pin_no']
        ).first()
        if self.component.config.get('open_pin') != cp.id:
            self.component.config['open_pin'] = cp.id
        cp = ColonelPin.objects.filter(
            colonel=colonel, no=self.component.config['close_pin_no']
        ).first()
        if self.component.config.get('close_pin') != cp.id:
            self.component.config['close_pin'] = cp.id
        for ctrl in self.component.config.get('controls', []):
            if 'pin_no' not in ctrl:
                continue
            if not ctrl.get('input').startswith('pin-'):
                continue
            cp = ColonelPin.objects.filter(
                colonel=colonel, no=ctrl['pin_no']
            ).first()
            if not cp:
                continue
            ctrl['input'] = f'pin-{cp.id}'
        self.component.save()


class TTLock(FleeDeviceMixin, Lock):
    gateway_class = FleetGatewayHandler
    config_form = TTLockConfigForm
    name = 'TTLock'
    discovery_msg = _("Please activate your TTLock so it can be discovered.")

    @classmethod
    def init_discovery(self, form_cleaned_data):
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
    def init_discovery(self, form_cleaned_data):
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