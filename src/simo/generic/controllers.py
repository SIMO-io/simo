import pytz
import datetime
import json
import time
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.urls import reverse_lazy
from simo.users.utils import get_system_user
from simo.core.models import Component
from simo.core.utils.helpers import get_random_string
from simo.core.middleware import get_current_instance
from simo.core.controllers import (
    BEFORE_SEND, ControllerBase,
    BinarySensor, NumericSensor, MultiSensor, Switch, Dimmer, DimmerPlus,
    RGBWLight,
    DoubleSwitch, TripleSwitch, QuadrupleSwitch, QuintupleSwitch
)
from .base_types import (
    ThermostatType, AlarmGroupType, WeatherType, IPCameraType,
    WateringType, StateSelectType, AlarmClockType
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
    ThermostatWidget, AlarmGroupWidget, IPCameraWidget,
    WateringWidget, StateSelectWidget, AlarmClockWidget,
    WeatherWidget
)
from .forms import (
    DimmableLightsGroupConfigForm, SwitchGroupConfigForm,
    ThermostatConfigForm, AlarmGroupConfigForm,
    IPCameraConfigForm, WeatherForm,
    WateringConfigForm, StateSelectForm, MainStateSelectForm,
    AlarmClockConfigForm, AudioAlertConfigForm
)

# ----------- Generic controllers -----------------------------



class DimmableLightsGroup(Dimmer):
    name = _("Dimmable Lights Group")
    gateway_class = GenericGatewayHandler
    config_form = DimmableLightsGroupConfigForm


class SwitchGroup(Switch):
    name = _("On/Off Group")
    gateway_class = GenericGatewayHandler
    config_form = SwitchGroupConfigForm


class Thermostat(ControllerBase):
    name = _("Thermostat")
    base_type = ThermostatType
    gateway_class = GenericGatewayHandler
    app_widget = ThermostatWidget
    config_form = ThermostatConfigForm
    admin_widget_template = 'admin/controller_widgets/thermostat.html'
    default_value = {
        'current_temp': 21, 'target_temp': 22,
        'heating': False, 'cooling': False
    }
    accepts_value = False

    @property
    def default_config(self):
        instance = get_current_instance()
        min = 4
        max = 36
        if instance and instance.units_of_measure == 'imperial':
            min = 40
            max = 95
        return {
            'temperature_sensor': 0, 'heaters': [], 'coolers': [],
            'engagement': 'dynamic',
            'min': min, 'max': max,
            'has_real_feel': False,
            'user_config': config_to_dict(self._get_default_user_config())
        }

    def _validate_val(self, value, occasion=None):
       return value

    def _get_default_user_config(self):
        instance = get_current_instance()
        if instance and instance.units_of_measure == 'imperial':
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
                             + int(timestr.split(':')[1]) * 60
                if start_second < current_second:
                    target_temp = target
            return target_temp

    def get_current_target_temperature(self):
        """Return active target temperature from user config.

        Computes the target based on hard/daily/weekly schedules and the
        current local time.
        Returns: float temperature.
        """
        data = self.component.config['user_config']
        if data['hard']['active']:
            return data['hard']['target']
        if data['daily']['active']:
            return self._get_target_from_options(data['daily']['options'])
        localtime = timezone.localtime()
        return self._get_target_from_options(
            data['weekly'][str(localtime.weekday() + 1)])

    def _evaluate(self):
        from simo.core.models import Component
        self.component.refresh_from_db()
        tz = pytz.timezone(self.component.zone.instance.timezone)
        timezone.activate(tz)
        temperature_sensor = Component.objects.filter(
            pk=self.component.config.get('temperature_sensor'),
            alive=True
        ).first()
        heaters = Component.objects.filter(
            pk__in=self.component.config.get('heaters', []),
            alive=True
        )
        coolers = Component.objects.filter(
            pk__in=self.component.config.get('coolers', []),
            alive=True
        )

        if not heaters and not coolers:
            self.component.error_msg = "No heaters/coolers"
            self.component.alive = False
            self.component.save()
            return

        if not temperature_sensor or not temperature_sensor.alive:
            self.component.error_msg = "No temperature sensor"
            self.component.alive = False
            self.component.save()
            return

        if self.component.error_msg or not self.component.alive:
            self.component.error_msg = None
            self.component.alive = True
            self.component.save()

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
        prefer_heating = True

        weather = Component.objects.filter(
            zone__instance=self.component.zone.instance,
            controller_uid=Weather.uid, alive=True
        ).first()
        if weather:
            try:
                feels_like = weather.value['main']['feels_like']
                if feels_like:
                    instance = get_current_instance()
                    if instance.units_of_measure == 'imperial':
                        feels_like = round((feels_like * 9 / 5) + 32, 1)
                    if target_temp < feels_like:
                        prefer_heating = False
            except:
                pass

        heating = False
        cooling = False

        if self.component.config.get('engagement', 'static') == 'static':
            low = target_temp - 0.25
            high = target_temp + 0.25
            if prefer_heating and heaters:
                heating = self._engage_heating(
                    heaters, current_temp, low, high
                )
                if not heating:
                    cooling = self._engage_cooling(
                        coolers, current_temp, low, high
                    )
            else:
                cooling = self._engage_cooling(
                    coolers, current_temp, low, high
                )
                if not cooling:
                    heating = self._engage_heating(
                        heaters, current_temp, low, high
                    )

        else:
            if prefer_heating and heaters:
                low = target_temp - 2.5
                high = target_temp + 0.5
                window = high - low
                reach = high - current_temp
                reaction_force = self._get_reaction_force(window, reach)
                if reaction_force:
                    heating = True
                self._engage_devices(heaters, reaction_force)
            elif coolers and not heating:
                low = target_temp - 1
                high = target_temp + 2
                window = high - low
                reach = current_temp - low
                reaction_force = self._get_reaction_force(window, reach)
                if reaction_force:
                    cooling = True
                self._engage_devices(coolers, reaction_force)

        self.component.set({
            'mode': mode,
            'current_temp': current_temp,
            'target_temp': target_temp,
            'heating': heating, 'cooling': cooling
        }, actor=get_system_user())

        self.component.error_msg = None
        self.component.alive = True
        self.component.save()


    def _engage_heating(self, heaters, current_temp, low, high):
        heating = False
        for heater in heaters:
            if current_temp < low:
                if heater.base_type == 'dimmer':
                    heater.max_out()
                else:
                    heater.turn_on()
                heating = True
            elif current_temp > high:
                heater.turn_off()
                heating = False
            else:
                if heater.value:
                    heating = True
                    break
        return heating


    def _engage_cooling(self, coolers, current_temp, low, high):
        cooling = False
        for cooler in coolers:
            if current_temp > high:
                if cooler.base_type == 'dimmer':
                    cooler.max_out()
                else:
                    cooler.turn_on()
                cooling = True
            elif current_temp < low:
                if cooler.value:
                    cooler.turn_off()
                cooling = False
            else:
                if cooler.value:
                    cooling = True
                    break
        return cooling


    def _get_reaction_force(self, window, reach):
        if reach > window:
            reaction_force = 100
        elif reach <= 0:
            reaction_force = 0
        else:
            reaction_force = reach / window * 100
        return reaction_force


    def _engage_devices(self, devices, reaction_force):
        for device in devices:
            if device.base_type == 'dimmer':
                device.output_percent(reaction_force)
            elif device.base_type == 'switch':
                if reaction_force == 100:
                    device.turn_on()
                elif reaction_force == 0:
                    device.turn_off()
                else:
                    device.pulse(30, reaction_force)


    def update_user_conf(self, new_conf):
        """Update thermostat user configuration.

        Parameters:
        - new_conf (dict): Partial or full user_config; validated and merged
          with defaults. Triggers re-evaluation after save.
        """
        self.component.refresh_from_db()
        self.component.config['user_config'] = validate_new_conf(
            new_conf,
            self.component.config['user_config'],
            self._get_default_user_config()
        )
        self.component.save()
        self._evaluate()


    def hold(self, temperature=None):
        """Hold a temporary target temperature.

        Parameters:
        - temperature (float|None): If provided, enables hard hold at this
          target; if None, disables hard hold to resume schedules.
        """
        if temperature != None:
            self.component.config['user_config']['hard'] = {
                'active': True, 'target': temperature
            }
        else:
            self.component.config['user_config']['hard']['active'] = False
        self.component.save()


class AlarmGroup(ControllerBase):
    name = _("Alarm Group")
    base_type = AlarmGroupType
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

    def send(self, value):
        """Set group state.

        Parameters:
        - value (str): 'armed', 'disarmed' (or 'breached' by system).
        Prefer using `arm()` and `disarm()` helpers.
        """
        return super().send(value)

    def arm(self):
        """Arm the entire group (children remain in their states)."""
        self.send('armed')

    def disarm(self):
        """Disarm the entire group."""
        self.send('disarmed')

    def get_children(self):
        """Return the queryset of child components that form this group."""
        return Component.objects.filter(
            pk__in=self.component.config['components']
        )

    def refresh_status(self):
        """Recompute and persist the group's aggregated security status."""
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


class Weather(ControllerBase):
    name = _("Weather")
    base_type = WeatherType
    gateway_class = GenericGatewayHandler
    config_form = WeatherForm
    app_widget = WeatherWidget
    admin_widget_template = 'admin/controller_widgets/weather.html'
    default_config = {}
    default_value = {}
    manual_add = False
    accepts_value = False

    def _validate_val(self, value, occasion=None):
        return value


class IPCamera(ControllerBase):
    name = _("IP Camera")
    base_type = IPCameraType
    gateway_class = GenericGatewayHandler
    app_widget = IPCameraWidget
    config_form = IPCameraConfigForm
    admin_widget_template = 'admin/controller_widgets/ip_camera.html'
    default_config = {'rtsp_address': ''}
    default_value = ''
    accepts_value = False

    def _validate_val(self, value, occasion=None):
        raise ValidationError("This component type does not accept set value!")

    def get_stream_socket_url(self):
        """Return the Channels WebSocket URL for live RTSP streaming."""
        return reverse_lazy(
            'ws-cam-stream', kwargs={'component_id': self.component.id},
            urlconf=settings.CHANNELS_URLCONF
        )


class Watering(ControllerBase):
    STATUS_CHOICES = (
        'stopped', 'running_program', 'running_custom',
        'paused_program', 'paused_custom'
    )
    name = _("Watering")
    base_type = WateringType
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

    def send(self, value):
        """Control watering.

        Parameters:
        - value (str): 'start', 'pause', 'reset', or
        - value (dict): {'status': <status>, 'program_progress': <minute>}
        Prefer `start()`, `pause()`, `reset()`, `set_program_progress()`.
        """
        return super().send(value)


    def start(self):
        """Start the watering program at current or last progress point."""
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
        """Alias for `start()` (for consistency with media-like controls)."""
        return self.start()

    def pause(self):
        """Pause the watering program and disengage all contours."""
        self.component.refresh_from_db()
        self.set({
            'status': 'paused_program',
            'program_progress': self.component.value.get('program_progress', 0)}
        )
        self.disengage_all()

    def reset(self):
        """Stop the watering program and reset progress to 0."""
        self.set({'status': 'stopped', 'program_progress': 0})
        self.disengage_all()

    def stop(self):
        """Alias for `reset()` to stop the program."""
        return self.reset()

    def _set_program_progress(self, program_minute, run=True):
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
        """Update AI-assistant computed watering parameters.

        Parameters:
        - data (dict): Partial program/schedule/contour updates from AI.
        """
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
        """Replace contours config and rebuild program accordingly.

        Parameters:
        - contours (list[dict]): Contour entries with uid and runtime updates.
        """
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
        """Replace schedule config and rebuild program accordingly."""
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
        """Turn off all configured watering contours immediately."""
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
                self.reset()
                self.start()


class AlarmClock(ControllerBase):
    name = _("Alarm Clock")
    base_type = AlarmClockType
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
    accepts_value = False

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

    def _tick(self):
        self.component.value = self._check_alarm(
            self.component.meta, self.component.value
        )
        self.component.save()

    def play_all(self):
        """Execute all enabled alarm events immediately for the current alarm."""
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
        """Cancel all enabled events of the current alarm and move to next alarm."""
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
        """Delay the current alarm by a number of minutes.

        Parameters:
        - mins (int): Minutes to postpone both the alarm and all its events.
        Returns updated clock state.
        """
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


class AudioAlert(Switch):
    gateway_class = GenericGatewayHandler
    name = _("Audio Alert")
    config_form = AudioAlertConfigForm

    def send(self, value):
        """Trigger or cancel an alert on all configured player components.

        Parameters:
        - value (bool): True to play alert; False to cancel.
        """
        for player in Component.objects.filter(
            id__in=self.component.config['players']
        ):
            if value:
                player.play_alert(self.component.id)
            else:
                self.component.set(False)
                player.cancel_alert()


class StateSelect(ControllerBase):
    gateway_class = GenericGatewayHandler
    name = _("State select")
    base_type = StateSelectType
    app_widget = StateSelectWidget
    config_form = StateSelectForm

    default_config = {'states': []}

    @property
    def default_value(self):
        try:
            return self.component.config['states'][0]['slug']
        except:
            return ''

    def _validate_val(self, value, occasion=None):
        available_options = [s.get('slug') for s in self.component.config.get('states', [])]
        if value not in available_options:
            raise ValidationError("Unsupported value!")
        return value

    def send(self, value):
        """Select state by slug.

        Parameters:
        - value (str): Must match one of configured state slugs.
        """
        return super().send(value)


class MainState(StateSelect):
    name = _("Main State")
    config_form = MainStateSelectForm
    default_value = 'day'

    default_config = {
        'is_main': True,
        'weekdays_morning_hour': 6,
        'weekends_morning_hour': 7,
        'away_on_no_action': 30,
        'sleeping_phones_hour': 21,
        'states': [
            {
                "icon": "sunrise", "name": "Morning", "slug": "morning",
                'help_text': "Morning hour to sunrise. Activates in dark time of a year."
            },
            {
                "icon": "house-day", "name": "Day", "slug": "day",
                'help_text': "From sunrise to sunset."
            },
            {
                "icon": "house-night", "name": "Evening", "slug": "evening",
                'help_text': "From sunrise to midnight"
            },
            {
                "icon": "moon-cloud", "name": "Night", "slug": "night",
                'help_text': "From midnight to sunrise or static morning hour."
            },
            {"icon": "snooze", "name": "Sleep time", "slug": "sleep"},
            {"icon": "house-person-leave", "name": "Away", "slug": "away"},
            {"icon": "island-tropical", "name": "Vacation", "slug": "vacation"}
        ]
    }

    def _get_day_evening_night_morning(self):
        from simo.automation.helpers import LocalSun
        sun = LocalSun(self.component.zone.instance.location)
        timezone.activate(self.component.zone.instance.timezone)
        localtime = timezone.localtime()

        # It is daytime if the sun is up!
        if not sun.is_night():
            return 'day'

        # it is evening if the sun is down at the evening
        if sun.get_sunset_time(localtime) < localtime:
            return 'evening'

        if localtime.weekday() < 5:
            if localtime.hour >= self.component.config['weekdays_morning_hour']:
                return 'morning'
        else:
            if localtime.hour >= self.component.config['weekends_morning_hour']:
                return 'morning'

        # 0 - 6AM and still dark
        return 'night'


    def _check_is_away(self, last_sensor_action):
        away_on_no_action = self.component.config.get('away_on_no_action')
        if not away_on_no_action:
            return False
        from simo.users.models import InstanceUser
        if InstanceUser.objects.filter(
            is_active=True, at_home=True, instance=self.component.zone.instance,
            role__is_person=True
        ).count():
            return False

        return (time.time() - last_sensor_action) // 60 >= away_on_no_action


    def _is_sleep_time(self):
        timezone.activate(self.component.zone.instance.timezone)
        localtime = timezone.localtime()
        if localtime.weekday() < 5:
            if localtime.hour < self.component.config['weekdays_morning_hour']:
                return True
        else:
            if localtime.hour < self.component.config['weekends_morning_hour']:
                return True
        sleeping_phones_hour = self.component.config.get(
            'sleeping_phones_hour'
        )
        if localtime.hour >= sleeping_phones_hour:
            return True

        return False


    def _owner_phones_on_charge(self, all_phones=False):
        sleeping_phones_hour = self.component.config.get('sleeping_phones_hour')
        if sleeping_phones_hour is None:
            return False

        from simo.users.models import InstanceUser

        phones_on_charge = []
        for iuser in InstanceUser.objects.filter(
            is_active=True, role__is_owner=True,
            instance=self.component.zone.instance,
            role__is_person=True
        ):
            # skipping users that are not at home
            if not iuser.at_home:
                continue
            phones_on_charge.append(iuser.phone_on_charge)


        if all_phones:
            return all(phones_on_charge)
        else:
            return any(phones_on_charge)





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
