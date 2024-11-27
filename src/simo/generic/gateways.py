import sys
import logging
import pytz
import json
import time
import multiprocessing
import threading
import traceback
from django.conf import settings
from django.utils import timezone
from django.db import connection as db_connection
from django.db.models import Q
import paho.mqtt.client as mqtt
from simo.core.models import Component
from simo.core.middleware import introduce_instance, drop_current_instance
from simo.core.gateways import BaseObjectCommandsGatewayHandler
from simo.core.forms import BaseGatewayForm
from simo.core.utils.logs import StreamToLogger
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



class GenericGatewayHandler(BaseObjectCommandsGatewayHandler):
    name = "Generic"
    config_form = BaseGatewayForm

    running_scripts = {}
    periodic_tasks = (
        ('watch_thermostats', 60),
        ('watch_alarm_clocks', 30),
        ('watch_watering', 60),
        ('watch_alarm_events', 1),
        ('watch_timers', 1)
    )

    terminating_scripts = set()

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
            introduce_instance(alarm_clock.zone.instance)
            tz = pytz.timezone(alarm_clock.zone.instance.timezone)
            timezone.activate(tz)
            alarm_clock.tick()

    def watch_watering(self):
        drop_current_instance()
        from .controllers import Watering
        for watering in Component.objects.filter(controller_uid=Watering.uid):
            introduce_instance(watering.zone.instance)
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
        from simo.generic.controllers import AlarmGroup

        payload = json.loads(msg.payload)
        drop_current_instance()
        component = get_event_obj(payload, Component)
        if not component:
            return
        introduce_instance(component.zone.instance)
        try:
            if component.controller_uid == AlarmGroup.uid:
                self.control_alarm_group(component, payload.get('set_val'))
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


    def watch_alarm_events(self):
        from .controllers import AlarmGroup
        drop_current_instance()
        for alarm in Component.objects.filter(
            controller_uid=AlarmGroup.uid, value='breached',
            meta__breach_start__gt=0
        ):
            for uid, event in alarm.controller.events_map.items():
                if uid in alarm.meta.get('events_triggered', []):
                    continue
                if time.time() - alarm.meta['breach_start'] < event['delay']:
                    continue
                try:
                    getattr(event['component'], event['breach_action'])()
                except Exception:
                    print(traceback.format_exc(), file=sys.stderr)
                if not alarm.meta.get('events_triggered'):
                    alarm.meta['events_triggered'] = [uid]
                else:
                    alarm.meta['events_triggered'].append(uid)
                alarm.save(update_fields=['meta'])

    def watch_timers(self):
        drop_current_instance()
        for component in Component.objects.filter(
            meta__timer_to__gt=0
        ).filter(meta__timer_to__lt=time.time()):
            component.meta['timer_to'] = 0
            component.meta['timer_start'] = 0
            component.save()
            try:
                component.controller._on_timer_end()
            except Exception as e:
                print(traceback.format_exc(), file=sys.stderr)


class DummyGatewayHandler(BaseObjectCommandsGatewayHandler):
    name = "Dummy"
    config_form = BaseGatewayForm

    def perform_value_send(self, component, value):
        component.controller.set(value)

