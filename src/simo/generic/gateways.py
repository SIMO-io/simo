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
from simo.core.middleware import introduce_instance
from simo.core.gateways import BaseObjectCommandsGatewayHandler
from simo.core.forms import BaseGatewayForm
from simo.core.utils.logs import StreamToLogger
from simo.core.events import GatewayObjectCommand, get_event_obj
from simo.core.loggers import get_gw_logger, get_component_logger



class BlindsRunner(threading.Thread):

    def __init__(self, blinds, *args, **kwargs):
        self.blinds = blinds
        self.target = self.blinds.value['target']
        self.position = self.blinds.value['position']
        self.open_duration = self.blinds.config.get('open_duration', 0) * 1000
        assert self.target >= -1
        assert self.target <= self.open_duration
        self.exit = multiprocessing.Event()
        super().__init__(*args, **kwargs)

    def run(self):
        try:
            self.open_switch = Component.objects.get(
                pk=self.blinds.config.get('open_switch')
            )
            self.close_switch = Component.objects.get(
                pk=self.blinds.config.get('close_switch')
            )
        except:
            self.done = True
            return
        self.start_position = self.blinds.value['position']
        self.position = self.blinds.value['position']
        self.start_time = time.time()
        self.last_save = time.time()
        while not self.exit.is_set():
            change = (time.time() - self.start_time) * 1000
            if self.target > self.start_position:
                self.position = self.start_position + change
                if self.position >= self.target:
                    self.blinds.set(
                        {'position': self.target, 'target': -1}
                    )
                    self.open_switch.turn_off()
                    self.close_switch.turn_off()
                    return
            else:
                self.position = self.start_position - change
                if self.position < self.target:
                    self.blinds.set({'position': self.target, 'target': -1})
                    self.open_switch.turn_off()
                    self.close_switch.turn_off()
                    return

            if self.last_save < time.time() - 1:
                self.blinds.set({'position': self.position})
                self.last_save = time.time()
            time.sleep(0.01)

    def terminate(self):
        self.exit.set()


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


class ScriptRunHandler(multiprocessing.Process):
    '''
      Threading offers better overall stability, but we use
      multiprocessing for Scripts so that they are better isolated and
      we are able to kill them whenever we need.
    '''
    component = None
    logger = None

    def __init__(self, component_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.component_id = component_id

    def run(self):
        db_connection.connect()
        self.component = Component.objects.get(id=self.component_id)
        tz = pytz.timezone(self.component.zone.instance.timezone)
        timezone.activate(tz)
        introduce_instance(self.component.zone.instance)
        self.logger = get_component_logger(self.component)
        sys.stdout = StreamToLogger(self.logger, logging.INFO)
        sys.stderr = StreamToLogger(self.logger, logging.ERROR)
        self.component.value = 'running'
        self.component.save(update_fields=['value'])

        if hasattr(self.component.controller, '_run'):
            def run_code():
                self.component.controller._run()
        else:
            code = self.component.config.get('code')
            def run_code():
                exec(code, globals())

            if not code:
                self.component.value = 'finished'
                self.component.save(update_fields=['value'])
                return
        print("------START-------")
        try:
            run_code()
        except:
            print("------ERROR------")
            self.component.value = 'error'
            self.component.save(update_fields=['value'])
            raise
        else:
            print("------FINISH-----")
            self.component.value = 'finished'
            self.component.save(update_fields=['value'])
            return


class GenericGatewayHandler(BaseObjectCommandsGatewayHandler):
    name = "Generic"
    config_form = BaseGatewayForm

    running_scripts = {}
    blinds_runners = {}
    periodic_tasks = (
        ('watch_thermostats', 60),
        ('watch_alarm_clocks', 30),
        ('watch_scripts', 10),
        ('watch_watering', 60),
        ('watch_alarm_events', 1),
        ('watch_timers', 1)
    )

    def watch_thermostats(self):
        from .controllers import Thermostat
        for thermostat in Component.objects.filter(
            controller_uid=Thermostat.uid
        ):
            tz = pytz.timezone(thermostat.zone.instance.timezone)
            timezone.activate(tz)
            thermostat.evaluate()

    def watch_alarm_clocks(self):
        from .controllers import AlarmClock
        for alarm_clock in Component.objects.filter(
            controller_uid=AlarmClock.uid
        ):
            tz = pytz.timezone(alarm_clock.zone.instance.timezone)
            timezone.activate(tz)
            alarm_clock.tick()

    def watch_scripts(self):
        # observe running scripts and drop the ones that are no longer alive
        dead_processes = []
        for id, process in self.running_scripts.items():
            if process.is_alive():
                continue
            component = Component.objects.filter(id=id).exclude(
                value__in=('error', 'finished')
            ).first()
            if component:
                logger = get_component_logger(component)
                logger.log(logging.INFO, "-------DEAD!-------")
                component.value = 'error'
                component.save()
            dead_processes.append(id)

        for id in dead_processes:
            self.running_scripts.pop(id)

        if dead_processes:
            # give 10s of air before we restart the scripts what were
            # detected to be dead.
            return

        from simo.generic.controllers import Script
        for script in Component.objects.filter(
            controller_uid=Script.uid,
            config__keep_alive=True
        ).exclude(value__in=('running', 'stopped', 'finished')):
            self.start_script(script)

    def watch_watering(self):
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
        self.exit = exit
        self.logger = get_gw_logger(self.gateway_instance.id)
        for task, period in self.periodic_tasks:
            threading.Thread(
                target=self._run_periodic_task, args=(exit, task, period), daemon=True
            ).start()

        from simo.generic.controllers import Script, IPCamera

        mqtt_client = mqtt.Client()
        mqtt_client.username_pw_set('root', settings.SECRET_KEY)
        mqtt_client.on_connect = self.on_mqtt_connect
        mqtt_client.on_message = self.on_mqtt_message
        mqtt_client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)

        # We presume that this is the only running gateway, therefore
        # if there are any running scripts, that is not true.
        for component in Component.objects.filter(
            controller_uid=Script.uid, value='running'
        ):
            component.value = 'error'
            component.save()

        # Start scripts that are designed to be autostarted
        # as well as those who are designed to be kept alive, but
        # got terminated unexpectedly
        for script in Component.objects.filter(
            base_type='script',
        ).filter(
            Q(config__autostart=True) |
            Q(value='error', config__keep_alive=True)
        ).distinct():
            self.start_script(script)

        for cam in Component.objects.filter(
            controller_uid=IPCamera.uid
        ):
            cam_watch = CameraWatcher(cam.id, exit)
            cam_watch.start()

        print("GATEWAY STARTED!")
        while not exit.is_set():
            mqtt_client.loop()
        mqtt_client.disconnect()

        for id, runner in self.blinds_runners.items():
            runner.terminate()

        script_ids = [id for id in self.running_scripts.keys()]
        for id in script_ids:
            self.stop_script(
                Component.objects.get(id=id), 'error'
            )

        while len(script_ids):
            time.sleep(0.1)

    def on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        command = GatewayObjectCommand(self.gateway_instance)
        mqtt_client.subscribe(command.get_topic())

    def on_mqtt_message(self, client, userdata, msg):
        print("Mqtt message: ", msg.payload)
        from simo.generic.controllers import (
            Script, Blinds, AlarmGroup, Gate
        )
        payload = json.loads(msg.payload)
        component = get_event_obj(payload, Component)
        if not component:
            return
        try:
            if isinstance(component.controller, Script):
                if payload.get('set_val') == 'start':
                    self.start_script(component)
                elif payload.get('set_val') == 'stop':
                    self.stop_script(component)
                return
            elif component.controller_uid == Blinds.uid:
                self.control_blinds(component, payload.get('set_val'))
            elif component.controller_uid == AlarmGroup.uid:
                self.control_alarm_group(component, payload.get('set_val'))
            elif component.controller_uid == Gate:
                self.control_gate(component, payload.get('set_val'))
            else:
                component.controller.set(payload.get('set_val'))
        except Exception:
            print(traceback.format_exc(), file=sys.stderr)


    def start_script(self, component):
        print("START SCRIPT %s" % str(component))
        if component.id in self.running_scripts:
            if self.running_scripts[component.id].is_alive():
                self.running_scripts[component.id].kill()
                component.value = 'error'
                component.save(update_fields=['value'])
        self.running_scripts[component.id] = ScriptRunHandler(
            component.id, daemon=True
        )
        self.running_scripts[component.id].start()

    def stop_script(self, component, stop_status='stopped'):
        if component.id not in self.running_scripts:
            if component.value == 'running':
                component.value = stop_status
                component.save(update_fields=['value'])
            return
        if self.running_scripts[component.id].is_alive():
            tz = pytz.timezone(component.zone.instance.timezone)
            timezone.activate(tz)
            logger = get_component_logger(component)
            if stop_status == 'error':
                logger.log(logging.INFO, "-------GATEWAY STOP-------")
            else:
                logger.log(logging.INFO, "-------STOP-------")
            self.running_scripts[component.id].terminate()

            def kill():
                start = time.time()
                terminated = False
                while start > time.time() - 2:
                    if not self.running_scripts[component.id].is_alive():
                        terminated = True
                        break
                    time.sleep(0.1)
                if not terminated:
                    if stop_status == 'error':
                        logger.log(logging.INFO, "-------GATEWAY KILL-------")
                    else:
                        logger.log(logging.INFO, "-------KILL!-------")
                    self.running_scripts[component.id].kill()

                component.value = stop_status
                component.save(update_fields=['value'])
                self.running_scripts.pop(component.id)
                logger.handlers = []

            threading.Thread(target=kill, daemon=True).start()

    def control_blinds(self, blinds, target):
        try:
            open_switch = Component.objects.get(
                pk=blinds.config['open_switch']
            )
            close_switch = Component.objects.get(
                pk=blinds.config['close_switch']
            )
        except:
            return

        blinds.set({'target': target})

        blinds_runner = self.blinds_runners.get(blinds.id)
        if blinds_runner:
            blinds_runner.terminate()

        if target == -1:
            open_switch.turn_off()
            close_switch.turn_off()

        elif target != blinds.value['position']:
            try:
                self.blinds_runners[blinds.id] = BlindsRunner(blinds)
                self.blinds_runners[blinds.id].daemon = True
            except:
                pass
            else:
                if target > blinds.value['position']:
                    close_switch.turn_off()
                    open_switch.turn_on()
                else:
                    open_switch.turn_off()
                    close_switch.turn_on()

                self.blinds_runners[blinds.id].start()

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


    def control_gate(self, gate, value):
        switch = Component.objects.filter(
            pk=gate.config.get('action_switch')
        ).first()
        if not switch:
            return

        if gate.config.get('action_method') == 'click':
            switch.click()
        else:
            if value == 'open':
                switch.turn_on()
            else:
                switch.turn_off()

    def watch_alarm_events(self):
        from .controllers import AlarmGroup
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

