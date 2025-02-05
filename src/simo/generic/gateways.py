import sys
import pytz
import json
import time
import threading
import traceback
from django.conf import settings
from django.utils import timezone
import paho.mqtt.client as mqtt
from simo.core.utils.helpers import get_self_ip
from simo.core.models import Component, PublicFile
from simo.core.middleware import drop_current_instance
from simo.core.gateways import BaseObjectCommandsGatewayHandler
from simo.core.forms import BaseGatewayForm
from simo.core.events import GatewayObjectCommand, get_event_obj
from simo.core.loggers import get_gw_logger, get_component_logger


class CameraWatcher(threading.Thread):

    def __init__(self, component_id, exit, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exit = exit
        self.component_id = component_id

    def run(self):
        if self.exit.is_set():
            return
        # component = Component.objects.get(id=self.component_id)
        # try:
        #     video = cv2.VideoCapture(component.config['rtsp_address'])
        #     last_shot = 0
        #     while not self.exit.is_set():
        #         _, frame = video.read()
        #         frame = cv2.resize(
        #             frame, (200, 200), interpolation=cv2.INTER_AREA
        #         )
        #         _, jpeg = cv2.imencode('.jpg', frame)
        #         if last_shot < time.time() - 10: # Take shot every 10 seconds.
        #             component.refresh_from_db()
        #             component.track_history = False
        #             component.value = base64.b64encode(
        #                 jpeg.tobytes()
        #             ).decode('ascii')
        #             component.save()
        #             last_shot = time.time()
        #     video.release()
        # except:
        #     try:
        #         video.release()
        #     except:
        #         pass
        #     time.sleep(5)
        #     self.run()



class GroupButtonsHandler:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_buttons = {}
        self.fade_directions = {}

    def watch_groups(self):
        from .controllers import DimmableLightsGroup, SwitchGroup
        current_group_buttons = {}
        for group_comp in Component.objects.filter(
            controller_uid__in=(DimmableLightsGroup.uid, SwitchGroup.uid)
        ):
            for ctrl in group_comp.config.get('controls', []):
                if ctrl['button'] not in current_group_buttons:
                    current_group_buttons[ctrl['button']] = set(group_comp.id)
                else:
                    current_group_buttons[ctrl['button']].add(group_comp.id)

                if ctrl['button'] not in self.group_buttons:
                    self.group_buttons[ctrl['button']] = set()
                if group_comp.id not in self.group_buttons[ctrl['button']]:
                    self.group_buttons[ctrl['button']].add(group_comp.id)
                    btn = Component.objects.filter(id=ctrl['button']).first()
                    if btn:
                        btn.on_change(self.watch_group_button)

        # remove groups and buttons that are no longer in use
        for btn_id, groups in self.group_buttons.items():
            if btn_id not in current_group_buttons:
                self.group_buttons[btn_id] = set()
                continue
            self.group_buttons[btn_id] = current_group_buttons[btn_id]


    def watch_group_button(self, button):
        group_ids = self.group_buttons.get(button.id)
        if not group_ids:
            return

        btn_type = button.config.get('btn_type', 'momentary')

        if btn_type == 'momentary':
            if button.value not in ('click', 'hold', 'up', 'double-click'):
                return
            for g_id in group_ids:
                group = Component.objects.filter(id=g_id).first()
                if not group:
                    continue
                if button.value == 'click':
                    group.toggle()
                elif button.value == 'double-click':
                    group.send(group.config.get('max', 100))
                elif button.value == 'down':
                    if self.fade_directions.get(group.id, 0) < 0:
                        self.fade_directions[group.id] = 1
                        group.fade_up()
                    else:
                        self.fade_directions[group.id] = -1
                        group.fade_down()
                elif button.value == 'up':
                    if self.fade_directions.get(group.id):
                        self.fade_directions[group.id] = 0
                        group.fade_stop()

        else: # toggle
            if button.value not in ('down', 'up'):
                return
            for g_id in group_ids:
                group = Component.objects.filter(id=g_id).first()
                if not group:
                    continue
                group.toggle()


# class AudioAlertsHandler:
#
#     def control_audio_alert(self, component, val):
#         if val:
#             public_file = PublicFile.objects.filter(
#                 component=component
#             ).first()
#             if not public_file:
#                 return
#             uri = f"http://{get_self_ip()}{public_file.get_absolute_url()}"
#             loop = component.config.get('loop', False)
#             for pl_id in component.config.get('players', []):
#                 player = Component.objects.filter(
#                     id=pl_id, base_type='audio-player'
#                 ).first()
#                 if not player:
#                     continue
#                 player.play_alert(
#                     uri,
#                     component.config.get('loop', False),
#                     component.config.get('volume', 50)
#                 )
#                 if not loop:
#                     def set_done(comp):
#                         comp.set(False)
#                     threading.Timer(
#                         component.config.get('duration', 1),
#                         set_done, args=[component]
#                     )
#             component.set(True)
#         else:
#             for pl_id in component.config.get('players', []):
#                 player = Component.objects.filter(
#                     id=pl_id, base_type='audio-player'
#                 ).first()
#                 if not player:
#                     continue
#                 player.cancel_alert()
#             component.set(False)


class GenericGatewayHandler(
    BaseObjectCommandsGatewayHandler, GroupButtonsHandler
):
    name = "Generic"
    config_form = BaseGatewayForm
    info = "Provides generic type components which use other components to operate like " \
           "thermostats, alarm groups, watering programs, alarm clocks," \
           "etc. "

    running_scripts = {}
    periodic_tasks = (
        ('watch_thermostats', 60),
        ('watch_alarm_clocks', 30),
        ('watch_watering', 60),
        ('watch_main_states', 60),
        ('watch_groups', 60)
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_sensor_actions = {}
        self.sensors_on_watch = {}
        self.sleep_is_on = {}
        self.last_set_state = None



    def watch_thermostats(self):
        from .controllers import Thermostat
        drop_current_instance()
        for thermostat in Component.objects.filter(
            controller_uid=Thermostat.uid
        ):
            tz = pytz.timezone(thermostat.zone.instance.timezone)
            timezone.activate(tz)
            thermostat.evaluate()

    def watch_alarm_clocks(self):
        from .controllers import AlarmClock
        drop_current_instance()
        for alarm_clock in Component.objects.filter(
            controller_uid=AlarmClock.uid
        ):
            tz = pytz.timezone(alarm_clock.zone.instance.timezone)
            timezone.activate(tz)
            alarm_clock.tick()

    def watch_watering(self):
        drop_current_instance()
        from .controllers import Watering
        for watering in Component.objects.filter(controller_uid=Watering.uid):
            tz = pytz.timezone(watering.zone.instance.timezone)
            timezone.activate(tz)
            if watering.value['status'] == 'running_program':
                watering.set_program_progress(
                    watering.value['program_progress'] + 1
                )
            else:
                watering.controller._perform_schedule()

    def run(self, exit):
        drop_current_instance()
        self.exit = exit
        self.logger = get_gw_logger(self.gateway_instance.id)
        for task, period in self.periodic_tasks:
            threading.Thread(
                target=self._run_periodic_task, args=(exit, task, period), daemon=True
            ).start()

        from simo.generic.controllers import IPCamera

        mqtt_client = mqtt.Client()
        mqtt_client.username_pw_set('root', settings.SECRET_KEY)
        mqtt_client.on_connect = self.on_mqtt_connect
        mqtt_client.on_message = self.on_mqtt_message
        mqtt_client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)

        for cam in Component.objects.filter(
            controller_uid=IPCamera.uid
        ):
            cam_watch = CameraWatcher(cam.id, exit)
            cam_watch.start()

        print("GATEWAY STARTED!")
        while not exit.is_set():
            mqtt_client.loop()
        mqtt_client.disconnect()


    def on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        command = GatewayObjectCommand(self.gateway_instance)
        mqtt_client.subscribe(command.get_topic())

    def on_mqtt_message(self, client, userdata, msg):
        print("Mqtt message: ", msg.payload)
        from simo.generic.controllers import AlarmGroup#, #AudioAlert

        payload = json.loads(msg.payload)
        drop_current_instance()
        component = get_event_obj(payload, Component)
        if not component:
            return
        try:
            if component.controller_uid == AlarmGroup.uid:
                self.control_alarm_group(component, payload.get('set_val'))
            # elif component.controller_uid == AudioAlert.uid:
            #     self.control_audio_alert(component, payload.get('set_val'))
            else:
                component.controller.set(payload.get('set_val'))
        except Exception:
            print(traceback.format_exc(), file=sys.stderr)


    def control_alarm_group(self, alarm_group, value):
        from simo.generic.controllers import AlarmGroup

        other_alarm_groups = {}
        stats = {
            'disarmed': 0, 'pending-arm': 0, 'armed': 0, 'breached': 0
        }

        for c_id in alarm_group.config['components']:
            slave = Component.objects.filter(pk=c_id).first()
            if not slave:
                continue
            if value == 'armed':
                if not slave.is_in_alarm():
                    slave.arm_status = 'armed'
                    stats['armed'] += 1
                else:
                    slave.arm_status = 'pending-arm'
                    stats['pending-arm'] += 1
            elif value == 'disarmed':
                stats['disarmed'] += 1
                slave.arm_status = 'disarmed'

            slave.do_not_update_alarm_group = True
            slave.save(update_fields=['arm_status'])

            for other_group in Component.objects.filter(
                controller_uid=AlarmGroup.uid,
                config__components__contains=slave.id
            ).exclude(pk=alarm_group.pk):
                other_alarm_groups[other_group.pk] = other_group

        alarm_group.value = value
        if stats['pending-arm']:
            alarm_group.value = 'pending-arm'
        alarm_group.config['stats'] = stats
        alarm_group.save()

        for pk, other_group in other_alarm_groups.items():
            other_group.refresh_status()


    def set_get_day_evening_night_morning(self, state):
        if state.value  not in ('day', 'night', 'evening', 'morning'):
            return
        new_state = state.get_day_evening_night_morning()
        if new_state == state.value:
            self.last_set_state = state.value
            return
        if self.last_set_state:
            # check if user maybe changed the state manually.
            # If that's the case, we should not intervene
            if new_state == 'day' and self.last_set_state not in ('night', 'morning'):
                return
            if new_state == 'evening' and self.last_set_state != 'day':
                return
            if new_state == 'night' and self.last_set_state != 'evening':
                return
            if new_state == 'morning' and self.last_set_state != 'night':
                return

        print(f"New main state of {state.zone.instance} - {new_state}")
        state.send(new_state)


    def watch_main_state(self, state):
        i_id = state.zone.instance.id
        self.set_get_day_evening_night_morning(state)

        if state.config.get('away_on_no_action'):
            if i_id not in self.last_sensor_actions:
                self.last_sensor_actions[i_id] = time.time()
            if state.id not in self.sensors_on_watch:
                self.sensors_on_watch[state.id] = {}
            for sensor in Component.objects.filter(
                zone__instance=state.zone.instance,
                base_type='binary-sensor', alarm_category='security'
            ):
                if sensor.id not in self.sensors_on_watch[state.id]:
                    self.sensors_on_watch[state.id][sensor.id] = i_id
                    sensor.on_change(self.security_sensor_change)

            if state.check_is_away(self.last_sensor_actions.get(i_id, 0)):
                if state.value != 'away':
                    print(f"New main state of "
                          f"{state.zone.instance} - away")
                    state.send('away')
            else:
                if state.value == 'away':
                    try:
                        new_state = state.get_day_evening_night_morning()
                    except:
                        new_state = 'day'
                    print(f"New main state of "
                          f"{state.zone.instance} - {new_state}")
                    state.send(new_state)

        if state.config.get('sleeping_phones_hour') is not None:
            if state.value != 'sleep':
                if state.is_sleep_time() and state.owner_phones_on_charge(True):
                    print(f"New main state of {state.zone.instance} - sleep")
                    state.send('sleep')
            else:
                if not state.owner_phones_on_charge(True) \
                and not state.is_sleep_time():
                    try:
                        new_state = state.get_day_evening_night_morning()
                    except:
                        new_state = 'day'
                    print(f"New main state of "
                          f"{state.zone.instance} - {new_state}")
                    state.send(new_state)


    def watch_main_states(self):
        drop_current_instance()
        from .controllers import MainState
        for state in Component.objects.filter(
            controller_uid=MainState.uid
        ).select_related('zone', 'zone__instance'):
            try:
                self.watch_main_state(state)
            except Exception as e:
                print(traceback.format_exc(), file=sys.stderr)


    def security_sensor_change(self, sensor):
        self.last_sensor_actions[
            sensor.zone.instance.id
        ] = time.time()



class DummyGatewayHandler(BaseObjectCommandsGatewayHandler):
    name = "Dummy"
    config_form = BaseGatewayForm
    info = "Provides dummy components that do absolutely anything, " \
           "but comes in super handy when configuring custom automations."

    def perform_value_send(self, component, value):
        component.controller.set(value)

