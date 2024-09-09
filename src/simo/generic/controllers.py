import time
import threading
import pytz
import datetime
import json
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.urls import reverse_lazy
from simo.conf import dynamic_settings
from simo.users.middleware import get_current_user, introduce
from simo.users.utils import get_system_user
from simo.core.events import GatewayObjectCommand
from simo.core.models import RUN_STATUS_CHOICES_MAP, Component
from simo.core.utils.helpers import get_random_string
from simo.core.utils.operations import OPERATIONS
from simo.core.controllers import (
    BEFORE_SEND, BEFORE_SET, ControllerBase,
    BinarySensor, NumericSensor, MultiSensor, Switch, Dimmer, DimmerPlus,
    RGBWLight, TimerMixin,
    DoubleSwitch, TripleSwitch, QuadrupleSwitch, QuintupleSwitch
)
from simo.core.utils.config_values import (
    BooleanConfigValue, FloatConfigValue,
    TimeTempConfigValue, ThermostatModeConfigValue,
    TimeConfigValue, ChoicesConfigValue,
    validate_new_conf, config_to_dict,
    ConfigException, has_errors
)
from .gateways import GenericGatewayHandler, DummyGatewayHandler
from .app_widgets import (
    ScriptWidget, ThermostatWidget, AlarmGroupWidget, IPCameraWidget,
    WeatherForecastWidget, GateWidget, BlindsWidget, SlidesWidget,
    WateringWidget, StateSelectWidget, AlarmClockWidget
)
from .forms import (
    ScriptConfigForm, PresenceLightingConfigForm,
    ThermostatConfigForm, AlarmGroupConfigForm,
    IPCameraConfigForm, WeatherForecastForm, GateConfigForm,
    BlindsConfigForm, WateringConfigForm, StateSelectForm,
    AlarmClockConfigForm
)

# ----------- Generic controllers -----------------------------

class Script(ControllerBase, TimerMixin):
    masters_only = True
    name = _("Script")
    base_type = 'script'
    gateway_class = GenericGatewayHandler
    app_widget = ScriptWidget
    config_form = ScriptConfigForm
    admin_widget_template = 'admin/controller_widgets/script.html'
    default_config = {'autostart': True, 'autorestart': True}
    default_value = 'stopped'

    def _validate_val(self, value, occasion=None):
        if occasion == BEFORE_SEND:
            if value not in ('start', 'stop'):
                raise ValidationError("Must be 'start' or 'stop'")
        elif occasion == BEFORE_SET:
            if value not in RUN_STATUS_CHOICES_MAP.keys():
                raise ValidationError(
                    "Invalid script controller status!"
                )
        return value

    def _prepare_for_send(self, value):
        if value == 'start':
            new_code = getattr(self.component, 'new_code', None)
            if new_code:
                self.component.new_code = None
                self.component.refresh_from_db()
                self.component.config['code'] = new_code
                self.component.save(update_fields=['config'])
        return value

    def _val_to_success(self, value):
        if value == 'start':
            return 'running'
        else:
            return 'stopped'

    def start(self, new_code=None):
        if new_code:
            self.component.new_code = new_code
        self.send('start')

    def play(self):
        return self.start()

    def stop(self):
        self.send('stop')

    def toggle(self):
        self.component.refresh_from_db()
        if self.component.value == 'running':
            self.send('stop')
        else:
            self.send('start')


class PresenceLighting(Script):
    masters_only = False
    name = _("Presence lighting")
    config_form = PresenceLightingConfigForm

    # script specific variables
    sensors = {}
    light_org_values = {}
    is_on = False
    turn_off_task = None

    def _run(self):
        while True:
            self._on_sensor()
            time.sleep(10)

    def _on_sensor(self, sensor=None):

        self.component.refresh_from_db()
        for id in self.component.config['presence_sensors']:
            if id not in self.sensors:
                sensor = Component.objects.filter(id=id).first()
                if sensor:
                    sensor.on_change(self._on_sensor)
                    self.sensors[id] = sensor

        if sensor:
            self.sensors[sensor.id] = sensor

        presence_values = [s.value for id, s in self.sensors.items()]
        if self.component.config.get('act_on', 0) == 0:
            must_on = any(presence_values)
        else:
            must_on = all(presence_values)

        additional_conditions_met = True
        for condition in self.component.config.get('conditions', []):
            if not additional_conditions_met:
                continue
            comp = Component.objects.filter(
                id=condition.get('component', 0)
            ).first()
            if not comp:
                continue
            op = OPERATIONS.get(condition.get('op'))
            if not op:
                continue
            if condition['op'] == 'in':
                if comp.value not in self._string_to_vals(condition['value']):
                    additional_conditions_met = False
                continue

            if not op(comp.value, condition['value']):
                additional_conditions_met = False

        if must_on and not additional_conditions_met:
            print("Presence detected, but additional conditions not met!")

        if must_on and additional_conditions_met and not self.is_on:
            print("Turn the lights ON!")
            self.is_on = True
            if self.turn_off_task:
                self.turn_off_task.cancel()
                self.turn_off_task = None
            self.light_org_values = {}
            for id in self.component.config['lights']:
                comp = Component.objects.filter(id=id).first()
                if not comp or not comp.controller:
                    continue
                self.light_org_values[comp.id] = comp.value
                comp.controller.send(self.component.config['on_value'])
            return

        if self.is_on:
            if not additional_conditions_met:
                return self._turn_it_off()
            if not any(presence_values):
                if not self.component.config.get('hold_time', 0):
                    return self._turn_it_off()
                if not self.turn_off_task:
                    self.turn_off_task = threading.Timer(
                        self.component.config['hold_time'] * 10,
                        self._turn_it_off
                    )

    def _turn_it_off(self):
        print("Turn the lights OFF!")
        self.is_on = False
        self.turn_off_task = None
        for id in self.component.config['lights']:
            comp = Component.objects.filter(id=id).first()
            if not comp or not comp.controller:
                continue
            if self.component.config['off_value'] == 0:
                comp.send(0)
            else:
                comp.send(self.light_org_values.get(comp.id, 0))


# TODO: Night lighting
#
# Lights: components (switches, dimmers)
# On value: 40
# Sunset offset (mins): negative = earlier, positive = later
# Save energy at night: 1 - 6 turn the lights completely off at night.


class Thermostat(ControllerBase):
    name = _("Thermostat")
    base_type = 'thermostat'
    gateway_class = GenericGatewayHandler
    app_widget = ThermostatWidget
    config_form = ThermostatConfigForm
    admin_widget_template = 'admin/controller_widgets/thermostat.html'
    default_value = {
        'current_temp': 21, 'target_temp': 22,
        'heating': False, 'cooling': False
    }

    @property
    def default_config(self):
        min = 3
        max = 36
        if self.component.zone.instance.units_of_measure == 'imperial':
            min = 36
            max = 100
        return {
            'temperature_sensor': 0, 'heater': 0, 'cooler': 0,
            'reaction_difference': 0, 'min': min, 'max': max,
            'has_real_feel': False,
            'user_config': config_to_dict(self._get_default_user_config())
        }

    def _validate_val(self, value, occasion=None):
        raise ValidationError("This component type does not accept set value!")

    def _get_default_user_config(self):
        if self.component.zone.instance.units_of_measure == 'imperial':
            target_temp = 70
            low_target = 60
            high_target = 75
        else:
            target_temp = 21
            low_target = 17
            high_target = 22

        day_options = {
            '24h': {
                'active': BooleanConfigValue(True),
                'target': FloatConfigValue(target_temp)
            },
            'custom': TimeTempConfigValue(
                [('7:00', high_target), ('20:00', low_target)]
            )
        }
        user_config = {
            'mode': ThermostatModeConfigValue('auto'),
            'use_real_feel': BooleanConfigValue(False),
            'hard': {
                'active': BooleanConfigValue(True),
                'target': FloatConfigValue(target_temp)
            },
            'daily': {
                'active': BooleanConfigValue(True),
                'options': day_options
            },
            'weekly': {
                "1": day_options, "2": day_options, "3": day_options,
                "4": day_options, "5": day_options, "6": day_options,
                "7": day_options
            }
        }
        return user_config

    def _get_target_from_options(self, options):
        if options['24h']['active']:
            return options['24h']['target']
        else:
            localtime = timezone.localtime()
            current_second = localtime.hour * 3600 \
                           + localtime.minute * 60 \
                           + localtime.second

            def sort_factor(item):
                return int(item[0].split(':')[0]) * 3600 + int(
                    item[0].split(':')[1]) * 60

            sorted_options = sorted(options['custom'], key=sort_factor)
            target_temp = sorted_options[-1][1]
            for timestr, target in sorted_options:
                start_second = int(timestr.split(':')[0]) * 3600 \
                             + int(timestr.split(':')[1] * 60)
                if start_second < current_second:
                    target_temp = target
            return target_temp

    def get_current_target_temperature(self):
        data = self.component.config['user_config']
        if data['hard']['active']:
            return data['hard']['target']
        if data['daily']['active']:
            return self._get_target_from_options(data['daily']['options'])
        localtime = timezone.localtime()
        return self._get_target_from_options(
            data['weekly'][str(localtime.weekday() + 1)])

    def evaluate(self):
        from simo.core.models import Component
        self.component.refresh_from_db()
        tz = pytz.timezone(self.component.zone.instance.timezone)
        timezone.activate(tz)
        temperature_sensor = Component.objects.filter(
            pk=self.component.config.get('temperature_sensor')
        ).first()
        heater = Component.objects.filter(
            pk=self.component.config.get('heater')
        ).first()
        cooler = Component.objects.filter(
            pk=self.component.config.get('cooler')
        ).first()

        if not temperature_sensor or not temperature_sensor.alive:
            self.component.error_msg = "No temperature sensor"
            self.component.alive = False
            self.component.save()
            return

        current_temp = temperature_sensor.value
        if temperature_sensor.base_type == MultiSensor.base_type:
            value_dict = {}
            for val in temperature_sensor.value:
                value_dict[val[0]] = val[1]

            current_temp = value_dict.get('temperature', 0)
            if self.component.config['user_config'].get('use_real_feel'):
                current_temp = value_dict.get('real_feel', 0)

        target_temp = self.get_current_target_temperature()
        mode = self.component.config['user_config'].get('mode', 'auto')

        self.component.value = {
            'mode': mode,
            'current_temp': current_temp,
            'target_temp': target_temp,
            'heating': False, 'cooling': False
        }

        low = target_temp - self.component.config['reaction_difference'] / 2
        high = target_temp + self.component.config['reaction_difference'] / 2

        if not get_current_user():
            introduce(get_system_user())

        if mode in ('auto', 'heater'):
            if (not heater or not heater.alive) and mode == 'heater':
                self.component.error_msg = "No heater"
                self.component.alive = False
                self.component.save()
                return
            if current_temp < low:
                if not heater.value:
                    heater.turn_on()
                self.component.value['heating'] = True
            elif current_temp > high:
                if heater.value:
                    heater.turn_off()
                self.component.value['heating'] = False
        if mode in ('auto', 'cooler') and cooler:
            if not cooler or not cooler.alive:
                if mode == 'cooler' or (not heater or not heater.alive):
                    print(f"No cooler or heater on {self.component}!")
                    self.component.alive = False
                    self.component.save()
                    return
            if current_temp > high:
                if not cooler.value:
                    cooler.turn_on()
                self.component.value['cooling'] = True
            elif current_temp < low:
                if cooler.value:
                    cooler.turn_off()
                self.component.value['cooling'] = False

        self.component.error_msg = None
        self.component.alive = True
        self.component.save()

    def update_user_conf(self, new_conf):
        self.component.refresh_from_db()
        self.component.config['user_config'] = validate_new_conf(
            new_conf,
            self.component.config['user_config'],
            self._get_default_user_config()
        )
        self.component.save()
        self.evaluate()

    def hold(self, temperature=None):
        if temperature != None:
            self.component.config['user_config']['hard'] = {
                'active': True, 'target': temperature
            }
        else:
            self.component.config['user_config']['hard']['active'] = False
        self.component.save()


class AlarmGroup(ControllerBase):
    name = _("Alarm Group")
    base_type = 'alarm-group'
    gateway_class = GenericGatewayHandler
    app_widget = AlarmGroupWidget
    config_form = AlarmGroupConfigForm
    default_config = {
        'components': [],
        'stats': {'disarmed': 0, 'pending-arm': 0, 'armed': 0, 'breached': 0}
    }
    default_value = 'disarmed'

    def _validate_val(self, value, occasion=None):
        if occasion == BEFORE_SEND:
            if value not in ('armed', 'disarmed', 'breached'):
                raise ValidationError(
                    "%s - invalid set value for Alarm group!" % str(value)
                )
        else:
            if value not in ('disarmed', 'pending-arm', 'armed', 'breached'):
                raise ValidationError(
                    "%s - invalid value received for Alarm group!" % str(value)
                )
        return value

    def arm(self):
        self.send('armed')

    def disarm(self):
        self.send('disarmed')

    def get_children(self):
        return Component.objects.filter(
            pk__in=self.component.config['components']
        )

    def refresh_status(self):
        stats = {
            'disarmed': 0, 'pending-arm': 0, 'armed': 0, 'breached': 0
        }
        for slave in Component.objects.filter(
            pk__in=self.component.config['components'],
        ):
            stats[slave.arm_status] += 1

        if stats['disarmed'] == len(self.component.config['components']):
            self.component.value = 'disarmed'
        elif stats['armed'] == len(self.component.config['components']):
            self.component.value = 'armed'
        elif stats['breached']:
            self.component.value = 'breached'
        else:
            self.component.value = 'pending-arm'

        self.component.config['stats'] = stats
        self.component.save()

    @cached_property
    def events_map(self):
        map = {}
        for entry in self.component.config.get('breach_events', []):
            if 'uid' not in entry:
                continue
            comp = Component.objects.filter(id=entry['component']).first()
            if not comp:
                continue
            map[entry['uid']] = json.loads(json.dumps(entry))
            map[entry['uid']].pop('uid')
            map[entry['uid']]['component'] = comp
        return map


class WeatherForecast(ControllerBase):
    name = _("Weather Forecast")
    base_type = 'weather-forecast'
    gateway_class = GenericGatewayHandler
    config_form = WeatherForecastForm
    app_widget = WeatherForecastWidget
    admin_widget_template = 'admin/controller_widgets/weather_forecast.html'
    default_config = {}
    default_value = {}

    def _validate_val(self, value, occasion=None):
        return value


class IPCamera(ControllerBase):
    name = _("IP Camera")
    base_type = 'ip-camera'
    gateway_class = GenericGatewayHandler
    app_widget = IPCameraWidget
    config_form = IPCameraConfigForm
    admin_widget_template = 'admin/controller_widgets/ip_camera.html'
    default_config = {'rtsp_address': ''}
    default_value = ''

    def _validate_val(self, value, occasion=None):
        raise ValidationError("This component type does not accept set value!")

    def get_stream_socket_url(self):
        return reverse_lazy(
            'ws-cam-stream', kwargs={'component_id': self.component.id},
            urlconf=settings.CHANNELS_URLCONF
        )


class Gate(ControllerBase, TimerMixin):
    name = _("Gate")
    base_type = 'gate'
    gateway_class = GenericGatewayHandler
    app_widget = GateWidget
    config_form = GateConfigForm
    admin_widget_template = 'admin/controller_widgets/gate.html'
    default_config = {}

    @property
    def default_value(self):
        return 'closed'

    def _validate_val(self, value, occasion=None):
        if occasion == BEFORE_SEND:
            if self.component.config.get('action_method') == 'click':
                if value != 'call':
                    raise ValidationError(
                        'Gate component understands only one command: '
                        '"call". You have provided: "%s"' % (str(value))
                    )
            else:
                if value not in ('call', 'open', 'close'):
                    raise ValidationError(
                        'This gate component understands only 3 commands: '
                        '"open", "close" and "call". You have provided: "%s"' %
                        (str(value))
                    )
        elif occasion == BEFORE_SET and value not in (
            'closed', 'open', 'open_moving', 'closed_moving'
        ):
            raise ValidationError(
                'Gate component can only be in 4 states:  '
                '"closed", "closed", "open_moving", "closed_moving". '
                'You have provided: "%s"' % (str(value))
            )
        return value

    def _set_on_the_move(self):
        def cancel_move():
            start_value = self.component.value
            start_sensor_value = self.component.config.get('sensor_value')
            move_duration = self.component.config.get(
                'gate_open_duration', 30
            ) * 1000
            # stay in moving state for user defined amount of seconds
            time.sleep(move_duration / 1000)
            self.component.refresh_from_db()
            if time.time() - self.component.config.get('last_call', 0) \
                < move_duration / 1000:
                # There was another call in between of this wait,
                # so we must skip this in favor of the new cancel_move function
                # that is currently running in parallel.
                return

            # If it is no longer on the move this process becomes obsolete
            # For example when open/close binary sensor detects closed event
            # gate value is immediately set to closed.
            if not self.component.value.endswith('moving'):
                return

            # Started from closed, sensor already picked up open event
            # therefore this must now be considered as open.
            if start_value.startswith('closed') \
            and self.component.value == 'open_moving' \
            and self.component.config.get('sensor_value'):
                self.component.set('open')
                return

            # In all other occasions we wait for another move_duration
            # and finish move anyways.
            time.sleep(move_duration / 1000)
            self.component.refresh_from_db()
            if self.component.value.endswith('moving'):
                self.component.set(self.component.value[:-7])

        self.component.refresh_from_db()
        self.component.config['last_call'] = time.time()
        self.component.save(update_fields=['config'])

        if not self.component.value.endswith('_moving'):
            self.component.set(self.component.value + '_moving')
        threading.Thread(target=cancel_move, daemon=True).start()

    def open(self):
        self.send('open')

    def close(self):
        self.send('close')

    def call(self):
        self.send('call')

    # TODO: This was in gateway class, however it
    # needs to be moved here or part of it back to the gateway
    # as we no longer have Event object.
    # if msg.topic == Event.TOPIC:
    # if isinstance(component.controller, Switch):
    #     value_change = payload['data'].get('value')
    #     if not value_change:
    #         return
    #
    #     # Handle Gate switches
    #     for gate in Component.objects.filter(
    #             controller_uid=Gate.uid, config__action_switch=component.id
    #     ):
    #         if gate.config.get('action_method') == 'toggle':
    #             gate.controller._set_on_the_move()
    #         else:
    #             if value_change.get('new') == False:
    #                 # Button released
    #                 # set stopped position if it was moving, or set moving if not.
    #                 if gate.value.endswith('moving'):
    #                     if gate.config.get('sensor_value'):
    #                         gate.set('open')
    #                     else:
    #                         gate.set('closed')
    #                 else:
    #                     gate.controller._set_on_the_move()
    #
    #     return
    #
    # elif isinstance(component.controller, BinarySensor):
    #     value_change = payload['data'].get('value')
    #     if not value_change:
    #         return
    #     # Handle Gate binary sensors
    #     for gate in Component.objects.filter(
    #             controller_uid=Gate.uid,
    #             config__open_closed_sensor=component.id
    #     ):
    #         gate.config['sensor_value'] = component.value
    #         gate.save(update_fields=['config'])
    #         # If sensor goes from False to True, while gate is moving
    #         # it usually means that gate just started the move and must stay in the move
    #         # user defined amount of seconds to represent actual gate movement.
    #         # Open state therefore is reached only after user defined duration.
    #         # If it was not in the move, then it simply means that it was
    #         # opened in some other way and we set it to open immediately.
    #         if component.value:
    #             if gate.value.endswith('moving'):
    #                 print("SET OPEN MOVING!")
    #                 gate.set('open_moving')
    #             else:
    #                 gate.set('open')
    #         # if binary sensor detects gate close event
    #         # we set gate value to closed immediately as it means that
    #         # gate is now truly closed and no longer moving.
    #         else:
    #             gate.set('closed')


class Blinds(ControllerBase, TimerMixin):
    name = _("Blind")
    base_type = 'blinds'
    gateway_class = GenericGatewayHandler
    config_form = BlindsConfigForm
    admin_widget_template = 'admin/controller_widgets/blinds.html'
    default_config = {}

    @property
    def app_widget(self):
        if self.component.config.get('control_mode') == 'slide':
            return SlidesWidget
        else:
            return BlindsWidget

    @property
    def default_value(self):
        # target and current positions in milliseconds, angle in degrees (0 - 180)
        return {'target': 0, 'position': 0, 'angle': 0}

    def _validate_val(self, value, occasion=None):

        if occasion == BEFORE_SEND:
            if isinstance(value, int) or isinstance(value, float):
                # legacy support
                value = {'target': int(value)}
            if 'target' not in value:
                raise ValidationError("Target value is required!")
            target = value.get('target')
            if type(target) not in (float, int):
                raise ValidationError(
                    "Bad target position for blinds to go."
                )
            if target > self.component.config.get('open_duration') * 1000:
                raise ValidationError(
                    "Target value lower than %d expected, "
                    "%d received instead" % (
                        self.component.config['open_duration'] * 1000,
                        target
                    )
                )
            if 'angle' in value:
                try:
                    angle = int(value['angle'])
                except:
                    raise ValidationError(
                        "Integer between 0 - 180 is required for blinds angle."
                    )
                if angle < 0 or angle > 180:
                    raise ValidationError(
                        "Integer between 0 - 180 is required for blinds angle."
                    )
            else:
                value['angle'] = self.component.value.get('angle', 0)

        elif occasion == BEFORE_SET:
            if not isinstance(value, dict):
                raise ValidationError("Dictionary is expected")
            for key, val in value.items():
                if key not in ('target', 'position', 'angle'):
                    raise ValidationError(
                        "'target', 'position' or 'angle' parameters are expected."
                    )
                if key == 'position':
                    if val < 0:
                        raise ValidationError(
                            "Positive integer expected for blind position"
                        )
                    if val > self.component.config.get('open_duration') * 1000:
                        raise ValidationError(
                            "Positive value is to big. Must be lower than %d, "
                            "but you have provided %d" % (
                                self.component.config.get('open_duration') * 1000, val
                            )
                        )

            self.component.refresh_from_db()
            if 'target' not in value:
                value['target'] = self.component.value.get('target')
            if 'position' not in value:
                value['position'] = self.component.value.get('position')
            if 'angle' not in value:
                value['angle'] = self.component.value.get('angle')

        return value

    def open(self):
        send_val = {'target': 0}
        angle = self.component.value.get('angle')
        if angle is not None and 0 <= angle <= 180:
            send_val['angle'] = angle
        self.send(send_val)

    def close(self):
        send_val = {'target': self.component.config['open_duration'] * 1000}
        angle = self.component.value.get('angle')
        if angle is not None and 0 <= angle <= 180:
            send_val['angle'] = angle
        self.send(send_val)

    def stop(self):
        send_val = {'target': -1}
        angle = self.component.value.get('angle')
        if angle is not None and 0 <= angle <= 180:
            send_val['angle'] = angle
        self.send(send_val)


class Watering(ControllerBase):
    STATUS_CHOICES = (
        'stopped', 'running_program', 'running_custom',
        'paused_program', 'paused_custom'
    )
    name = _("Watering")
    base_type = 'watering'
    gateway_class = GenericGatewayHandler
    config_form = WateringConfigForm
    app_widget = WateringWidget
    default_value = {'status': 'stopped', 'program_progress': 0}

    @property
    def default_config(self):
        return {
            'contours': [],
            'program': {'flow': [], 'duration': 0},
            'ai_assist': True, 'soil_type': 'loamy', 'ai_assist_level': 50,
            'schedule': config_to_dict(self._get_default_schedule()),
            'estimated_moisture': 50,
        }


    def _validate_val(self, value, occasion=None):
        if occasion == BEFORE_SEND:
            if value not in ('start', 'pause', 'reset'):
                raise ValidationError(
                    "Accepts only start, pause and reset expected. "
                    "Got: %s" % str(value)
                )
        else:
            if not isinstance(value, dict):
                raise ValidationError("Dictionary is expected")
            for key, val in value.items():
                if key not in ('status', 'program_progress'):
                    raise ValidationError(
                        "'status' or 'program_progress' parameter expected."
                    )
                if key == 'program_progress':
                    if val < 0 or val > self.component.config['program']['duration']:
                        raise ValidationError(
                            "Number in range of 0 - %s expected for program_progress. "
                            "Got: %s" % (
                                self.component.config['program']['duration'],
                                str(val)
                            )
                        )
                elif key == 'status':
                    if val not in self.STATUS_CHOICES:
                        if val < 0 or val > 100:
                            raise ValidationError(
                                "One of %s expected. Got: %s" % (
                                    self.STATUS_CHOICES, str(val)
                                )
                            )
        return value


    def start(self):
        self.component.refresh_from_db()
        if not self.component.value.get('program_progress', 0):
            self.component.meta['last_run'] = timezone.now().timestamp()
            self.component.save()
        self.set(
            {'status': 'running_program',
             'program_progress': self.component.value['program_progress']}
        )
        self.set_program_progress(self.component.value['program_progress'])

    def play(self):
        return self.start()

    def pause(self):
        self.component.refresh_from_db()
        self.set({
            'status': 'paused_program',
            'program_progress': self.component.value.get('program_progress', 0)}
        )
        self.disengage_all()

    def reset(self):
        self.set({'status': 'stopped', 'program_progress': 0})
        self.disengage_all()

    def stop(self):
        return self.reset()

    def set_program_progress(self, program_minute, run=True):
        engaged_contours = []
        for flow_data in self.component.config['program']['flow']:
            if flow_data['minute'] <= program_minute:
                engaged_contours = flow_data['contours']
            else:
                break
        for contour_data in self.component.config['contours']:
            try:
                switch = Component.objects.get(pk=contour_data['switch'])
            except Component.DoesNotExist:
                continue
            if run:
                if switch.timer_engaged():
                    switch.stop_timer()
                if contour_data['uid'] in engaged_contours:
                    switch.turn_on()
                else:
                    switch.turn_off()

        if program_minute > self.component.config['program']['duration']:
            self.set({'status': 'stopped', 'program_progress': 0})
        else:
            if run:
                status = 'running_program'
            else:
                self.component.refresh_from_db()
                status = 'paused_program' if program_minute > 0 else 'stopped'
            self.set(
                {'program_progress': program_minute, 'status': status}
            )

    def ai_assist_update(self, data):
        for key, val in data.items():
            assert key in ('ai_assist', 'soil_type', 'ai_assist_level')
            if key == 'ai_assist':
                assert type(val) == bool
            elif key == 'soil_type':
                assert val in (
                    'loamy', 'silty', 'sandy', 'clay', 'peaty', 'chalky'
                )
            elif key == 'ai_assist_level':
                assert 0 <= val <= 100
        self.component.config.update(data)
        self.component.save()

    def contours_update(self, contours):
        current_contours = {
            c['uid']: c
            for c in self.component.config.get('contours')
        }
        new_contours = []
        for contour_data in contours:
            assert contour_data['uid'] in current_contours
            new_contour = current_contours[contour_data['uid']]
            new_contour['runtime'] = contour_data['runtime']
            new_contours.append(new_contour)
        assert len(new_contours) == len(self.component.config.get('contours'))
        self.component.config.update({'contours': contours})
        self.component.config.update({'program': self._build_program(contours)})
        self.component.save()

    def schedule_update(self, new_schedule):
        self.component.refresh_from_db()
        self.component.config['schedule'] = validate_new_conf(
            new_schedule,
            self.component.config['schedule'],
            self._get_default_schedule()
        )
        self.component.config['next_run'] = self._get_next_run()
        self.component.save()

    def _get_default_schedule(self):
        morning_time = TimeConfigValue(['5:00'])
        user_config = {
            'mode': ChoicesConfigValue('off', ['off', 'daily', 'weekly']),
            'daily': morning_time,
            'weekly': {
                "1": morning_time, "2": morning_time, "3": morning_time,
                "4": morning_time, "5": morning_time, "6": morning_time,
                "7": morning_time
            }
        }
        return user_config

    def _build_program(self, contours):

        for c in contours:
            c['occupation'] = int(c['occupation'])
            c['runtime'] = int(c['runtime'])
        contours_map = {c['uid']: c for c in contours}
        next_contour = 0
        engaged_contours = {}
        occupied_stream = 0
        program = []
        minute = 0
        while next_contour < len(contours) or engaged_contours:
            stop_contours = []
            for c_uid, engaged_minute in engaged_contours.items():
                if contours_map[c_uid]['runtime'] <= minute - engaged_minute:
                    stop_contours.append(c_uid)

            for stop_uid in stop_contours:
                engaged_contours.pop(stop_uid)
                occupied_stream -= contours_map[stop_uid]['occupation']

            start_contours = []
            while next_contour < len(contours) \
                and 100 - occupied_stream >= contours[next_contour]['occupation']:
                start_contours.append(contours[next_contour]['uid'])
                engaged_contours[contours[next_contour]['uid']] = minute
                occupied_stream += contours[next_contour]['occupation']
                next_contour += 1

            if start_contours or stop_contours:
                program.append(
                    {
                        'minute': minute,
                        'contours': [
                            uid for uid, start_m in engaged_contours.items()
                        ]
                    }
                )

            minute += 1

        if program:
            return {'duration': program[-1]['minute'] - 1, 'flow': program}
        return {'duration': 0, 'flow': []}

    def disengage_all(self):
        for contour_data in self.component.config['contours']:
            try:
                switch = Component.objects.get(pk=contour_data['switch'])
            except Component.DoesNotExist:
                continue
            if switch.timer_engaged():
                switch.stop_timer()
            switch.turn_off()

    def _get_next_run(self):
        if self.component.config['schedule']['mode'] == 'off':
            return

        localtime = timezone.localtime()
        local_minute = localtime.hour * 60 + localtime.minute
        local_day_timestamp = localtime.timestamp() - (
            localtime.hour * 60 * 60 + localtime.minute * 60 + localtime.second
        )
        if self.component.config['schedule']['mode'] == 'daily':
            times_to_start = self.component.config['schedule']['daily']
            if not times_to_start:
                return

            first_run_minute = 0
            for i, time_str in enumerate(times_to_start):
                hour, minute = time_str.split(':')
                minute_to_start = int(hour) * 60 + int(minute)
                if i == 0:
                    first_run_minute = minute_to_start
                if minute_to_start > local_minute:
                    return local_day_timestamp + minute_to_start * 60

            return local_day_timestamp + 24*60*60 + first_run_minute*60
        else:
            for i in range(8):
                current_weekday = localtime.weekday() + 1 + i
                if current_weekday > 7:
                    current_weekday = 1
                times_to_start = self.component.config['schedule']['weekly'][
                    str(current_weekday)
                ]
                if not times_to_start:
                    continue

                for time_str in times_to_start:
                    hour, minute = time_str.split(':')
                    minute_to_start = int(hour) * 60 + int(minute)
                    if minute_to_start > local_minute or i > 0:
                        return local_day_timestamp + \
                               i*24*60*60 + minute_to_start * 60
            return

    def _perform_schedule(self):
        self.component.refresh_from_db()
        next_run = self._get_next_run()
        if self.component.meta.get('next_run') != next_run:
            self.component.meta['next_run'] = next_run
            self.component.save()

        if self.component.value['status'] == 'running_program':
            return
        if self.component.config['schedule']['mode'] == 'off':
            return

        localtime = timezone.localtime()
        if self.component.config['schedule']['mode'] == 'daily':
            times_to_start = self.component.config['schedule']['daily']
        else:
            times_to_start = self.component.config['schedule']['weekly'][
                str(localtime.weekday() + 1)
            ]
        if not times_to_start:
            if self.component.meta.get('next_run'):
                self.component.meta['next_run'] = None
                self.component.save()
            return

        gap = 30
        local_minute = localtime.hour * 60 + localtime.minute

        for time_str in times_to_start:
            hour, minute = time_str.split(':')
            minute_to_start = int(hour) * 60 + int(minute)
            if local_minute < gap:
                # handling midnight
                offset = gap*2
                local_minute += offset
                minute_to_start += offset
                if minute_to_start > 24*60:
                    minute_to_start -= 24*60

            if minute_to_start <= local_minute < minute_to_start + gap:
                introduce(get_system_user())
                self.reset()
                self.start()


class AlarmClock(ControllerBase):
    name = _("Alarm Clock")
    base_type = 'alarm-clock'
    gateway_class = GenericGatewayHandler
    config_form = AlarmClockConfigForm
    app_widget = AlarmClockWidget
    default_config = {}
    default_value = {
        'in_alarm': False,
        'events': [],
        'events_triggered': [],
        'alarm_timestamp': None
    }

    def _validate_val(self, value, occasion=None):
        # this component does not accept value set.
        raise ValidationError("Unsupported value!")


    def set_user_config(self, data):
        # [{
        #     "uid": "54658FDS",
        #     "name": "Labas rytas!",
        #     "week_days": [1, 2, 3, 4, 5, 6 , 7],
        #     "time": "7:00",
        #     "events": [
        #         {"uid": "25F8H4R", "name": "Atsidaro užuolaida", "offset": -60, "component": 5, "play_action": "turn_on", "reverse_action": "turn_off", "enabled": True},
        #         {"uid": "8F5Y2D5", "name": "Groja paukštukai", "offset": -10, "component": 20, "play_action": "lock", "reverse_action": "unlock", "enabled": True},
        #         {"uid": "22fGROP", "name": "Groja muzika", "offset": 0, "component": 35, "play_action": "play", "reverse_action": "stop", "enabled": True}},
        #     ]
        # }]

        if not isinstance(data, list):
            raise ValidationError("List of alarms is required!")

        errors = []
        for i, alarm in enumerate(data):
            alarm_error = {}
            if 'name' not in alarm:
                alarm_error['name'] = "This field is required!"
            if 'week_days' not in alarm:
                alarm_error['week_days'] = "This field is required!"
            elif not isinstance(alarm['week_days'], list):
                alarm_error['week_days'] = "List of integers is required!"
            else:
                for day in alarm['week_days']:
                    if not isinstance(day, int):
                        alarm_error['week_days'] = "List of integers is required!"
                        break
                    if not 0 < day < 8:
                        alarm_error['week_days'] = "Days must be 1 - 7"
                        break

                if len(alarm['week_days']) > 7:
                    alarm_error['week_days'] = "There are no more than 7 days in a week!"

            if not alarm.get('time'):
                alarm_error['time'] = "This field is required!"

            try:
                hour, minute = alarm['time'].split(':')
                hour = int(hour)
                minute = int(minute)
            except:
                alarm_error['time'] = "Bad alarm clock time"
            else:
                if not 0 <= hour < 24:
                    alarm_error['time'] = f"Bad hour of {alarm['time']}"
                elif not 0 <= minute < 60:
                    alarm_error['time'] = f"Bad minute of {alarm['time']}"

            alarm_error['events'] = []
            for event in alarm.get('events', []):
                event_error = {}
                if 'offset' not in event:
                    event_error['offset'] = "This field is required!"
                elif not isinstance(event['offset'], int):
                    event_error['offset'] = "Offset must be an integer of minutes"
                elif not -120 < event['offset'] < 120:
                    event_error['offset'] = "No more than 2 hours of offset is allowed"

                if not event.get('name'):
                    event_error['name'] = "This field is required!"

                comp = None
                if not event.get('component'):
                    event_error['component'] = "This field is required!"
                else:
                    comp = Component.objects.filter(
                        zone__instance=self.component.zone.instance,
                        pk=event['component']
                    ).first()
                    # if not comp:
                    #     event_error['component'] = \
                    #         f"No such a component on " \
                    #         f"{self.component.zone.instance}"

                if not event.get('play_action'):
                    event_error['play_action'] = "This field is required!"
                else:
                    if comp and not hasattr(comp, event['play_action']):
                        event_error['play_action'] = "Method unavailable on this component"

                if event.get('reverse_action') and comp \
                and not hasattr(comp, event['reverse_action']):
                    event_error['reverse_action'] = "Method unavailable on this component"

                if 'enabled' not in event:
                    event_error['enabled'] = "This field is required!"

                if not event.get('uid'):
                    event['uid'] = get_random_string(6)

                alarm_error['events'].append(event_error)

            errors.append(alarm_error)

            if not alarm.get('uid'):
                alarm['uid'] = get_random_string(6)

        if has_errors(errors):
            raise ConfigException(errors)

        self.component.meta = data
        self.component.value = self._check_alarm(data, self.component.value)
        self.component.save()

        return data

    def _execute_event(self, event, forward=True):
        if not event.get('enabled'):
            print("Event is not enabled!")
            return
        if forward:
            print(f"Fire event {event['uid']}!")
        else:
            print(f"Reverse event {event['uid']}!")
        comp = Component.objects.filter(id=event['component']).first()
        if comp:
            if forward:
                action_name = 'play_action'
            else:
                action_name = 'reverse_action'
            action = event.get(action_name)
            action = getattr(comp, action, None)
            if action:
                action()


    def _check_alarm(self, alarms, current_value):

        if 'events' not in current_value:
            current_value['events'] = []
        if 'events_triggered' not in current_value:
            current_value['events_triggered'] = []
        if 'in_alarm' not in current_value:
            current_value['in_alarm'] = False
        if 'alarm_timestamp' not in current_value:
            current_value['alarm_timestamp'] = None

        localtime = timezone.localtime()
        weekday = localtime.weekday() + 1

        remove_ignores = []
        for ignore_alarm_uid, timestamp in current_value.get(
            'ignore_alarms',{}
        ).items():
            # if ignore alarm entry is now past the current time + maximum offset
            # drop it out from ignore_alarms map
            if timestamp + 60 < localtime.timestamp():
                print(
                    f"remove ignore alarm because "
                    f"{timestamp} < {localtime.timestamp()}"
                )
                remove_ignores.append(ignore_alarm_uid)
        for ignore_alarm_uid in remove_ignores:
            current_value['ignore_alarms'].pop(ignore_alarm_uid, None)


        if not current_value['in_alarm'] and alarms:
            next_alarm = None

            alarms = json.loads(json.dumps(alarms))
            for alarm in alarms:
                if alarm.get('enabled') == False:
                    continue
                hour, minute = alarm['time'].split(':')
                hour = int(hour)
                minute = int(minute)

                week_days = alarm['week_days']
                week_days = list(set(week_days))
                week_days.sort()
                week_days = week_days + [d + 7 for d in week_days]
                for wd in week_days:
                    alarm = json.loads(json.dumps(alarm))
                    if wd < weekday:
                        continue
                    days_diff = wd - weekday
                    if days_diff == 0 \
                        and hour * 60 + minute < localtime.hour * 60 + localtime.minute:
                        continue

                    next_alarm_datetime = datetime.datetime(
                        year=localtime.year, month=localtime.month,
                        day=localtime.day,
                        tzinfo=localtime.tzinfo
                    ) + datetime.timedelta(
                        minutes=minute + hour * 60 + days_diff * 24 * 60)
                    alarm['next_datetime'] = str(next_alarm_datetime)
                    next_alarm_timestamp = next_alarm_datetime.timestamp()
                    alarm['next_timestamp'] = next_alarm_timestamp
                    if not next_alarm or next_alarm['next_timestamp'] > \
                        alarm['next_timestamp']:
                        if current_value.get(
                            'ignore_alarms', {}
                        ).get(alarm['uid'], 0) + 60 > alarm['next_timestamp']:
                            # user already played through or canceled this particular alarm
                            continue
                        next_alarm = alarm
                        break

            if next_alarm:
                current_value['alarm_timestamp'] = next_alarm['next_timestamp']
                current_value['alarm_datetime'] = next_alarm['next_datetime']
                current_value['alarm_uid'] = next_alarm['uid']
                current_value['alarm_name'] = next_alarm['name']
                for event in next_alarm['events']:
                    event['fire_timestamp'] = next_alarm['next_timestamp'] + \
                                              event['offset'] * 60
                next_alarm['events'].sort(key=lambda el: el['fire_timestamp'])
                current_value['events'] = next_alarm['events']

            else:
                return {
                    'in_alarm': False,
                    'events': [],
                    'events_triggered': [],
                    'alarm_timestamp': None,
                    'ignore_alarms': current_value.get('ignore_alarms', {})
                }

        # At this point there is an alarm that we are looking forward or we are in it already

        if current_value.get('alarm_uid') in current_value.get('ignore_alarms', {}):
            return current_value

        for event in current_value['events']:
            if event['fire_timestamp'] <= localtime.timestamp():
                if not event.get('enabled'):
                    continue
                if event['uid'] in current_value['events_triggered']:
                    continue
                introduce(get_system_user())
                self._execute_event(event)
                current_value['events_triggered'].append(event['uid'])

        if not current_value['in_alarm']:
            current_value['in_alarm'] = bool(current_value['events_triggered'])

        # If alarm time is in the past and all events executed move to next alarm
        if current_value['in_alarm'] \
        and current_value['alarm_timestamp'] + 60 < localtime.timestamp() \
        and len(current_value['events_triggered']) >= len(
            [e for e in current_value['events'] if e.get('enabled')]
        ):
            current_value = {
                'in_alarm': False,
                'events': [],
                'events_triggered': [],
                'alarm_timestamp': None,
                'ignore_alarms': current_value.get('ignore_alarms', None)
            }
            return self._check_alarm(alarms, current_value)

        return current_value

    def tick(self):
        self.component.value = self._check_alarm(
            self.component.meta, self.component.value
        )
        self.component.save()

    def play_all(self):
        alarms = self.component.meta
        current_value = self.component.value

        if not current_value.get('in_alarm'):
            raise ValidationError("Nothing to play, we are not in alarm.")

        # default fire timestamp in case there are no events
        event = {'fire_timestamp': current_value['alarm_timestamp']}
        for event in current_value.get('events', []):
            if not event.get('enabled'):
                continue
            if event['uid'] not in current_value.get('events_triggered', []):
                self._execute_event(event)

        if 'ignore_alarms' not in current_value:
            current_value['ignore_alarms'] = {}

        current_value['ignore_alarms'][current_value['alarm_uid']] = event[
            'fire_timestamp']

        current_value = {
            'in_alarm': False,
            'events': [],
            'events_triggered': [],
            'alarm_timestamp': None,
            'ignore_alarms': current_value.get('ignore_alarms', {})
        }

        self.component.value = self._check_alarm(alarms, current_value)
        self.component.save()

        return self.component.value


    def cancel_all(self):
        alarms = self.component.meta
        current_value = self.component.value

        if not current_value.get('in_alarm'):
            raise ValidationError("Nothing to cancel, we are not in alarm.")

        # default fire timestamp in case there are no events
        event = {'fire_timestamp': current_value['alarm_timestamp']}
        for event in current_value.get('events', []):
            if not event.get('enabled'):
                continue
            if event['uid'] in current_value.get('events_triggered', []):
                self._execute_event(event, False)

        if 'ignore_alarms' not in current_value:
            current_value['ignore_alarms'] = {}

        current_value['ignore_alarms'][current_value['alarm_uid']] = event[
            'fire_timestamp']

        current_value = {
            'in_alarm': False,
            'events': [],
            'events_triggered': [],
            'alarm_timestamp': None,
            'ignore_alarms': current_value.get('ignore_alarms', {})
        }

        self.component.value = self._check_alarm(alarms, current_value)
        self.component.save()
        return self.component.value

    def snooze(self, mins):
        current_value = self.component.value
        localtime = timezone.localtime()
        if not current_value.get('in_alarm'):
            print("Nothing to do, we are not in alarm.")
            return current_value

        current_value['alarm_timestamp'] += mins * 60
        current_value['alarm_datetime'] = str(datetime.datetime.fromtimestamp(
            current_value['alarm_timestamp'],
        ).astimezone(tz=timezone.localtime().tzinfo))
        events_triggered = []
        for event in current_value['events']:
            event['fire_timestamp'] += mins * 60
            if event['uid'] in current_value['events_triggered']:
                if event['fire_timestamp'] > localtime.timestamp():
                    self._execute_event(event, False)
                else:
                    events_triggered.append(event['uid'])
        current_value['events_triggered'] = events_triggered

        self.component.value = current_value
        self.component.save()

        return current_value


class StateSelect(ControllerBase):
    gateway_class = GenericGatewayHandler
    name = _("State select")
    base_type = 'state-select'
    app_widget = StateSelectWidget
    config_form = StateSelectForm

    default_config = {'states': []}
    default_value = ''

    def _validate_val(self, value, occasion=None):
        available_options = [s.get('slug') for s in self.component.config.get('states', [])]
        if value not in available_options:
            raise ValidationError("Unsupported value!")
        return value


# ----------- Dummy controllers -----------------------------

class DummyBinarySensor(BinarySensor):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'


class DummyNumericSensor(NumericSensor):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'


class DummyMultiSensor(MultiSensor):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'


class DummySwitch(Switch):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'


class DummyDoubleSwitch(DoubleSwitch):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'


class DummyTripleSwitch(TripleSwitch):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'


class DummyQuadrupleSwitch(QuadrupleSwitch):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'


class DummyQuintupleSwitch(QuintupleSwitch):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'


class DummyDimmer(Dimmer):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'

    def _prepare_for_send(self, value):
        if self.component.config.get('inverse'):
            value = self.component.config.get('max') - value
        return value


class DummyDimmerPlus(DimmerPlus):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'


class DummyRGBWLight(RGBWLight):
    gateway_class = DummyGatewayHandler
    info_template_path = 'generic/controllers_info/dummy.md'
