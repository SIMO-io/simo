import sys
import cv2
import logging
import base64
import pytz
from logging.handlers import RotatingFileHandler
import json
import time
import multiprocessing
import threading
from django.conf import settings
from django.utils import timezone
from django.db import close_old_connections, connection as db_connection
import paho.mqtt.client as mqtt
from simo.core.models import Component
from simo.core.gateways import BaseObjectCommandsGatewayHandler
from simo.core.forms import BaseGatewayForm
from simo.core.utils.logs import StreamToLogger
from simo.core.events import ObjectCommand, Event, get_event_obj
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
      Threading offers better overall stability, but we must use
      multiprocessing for Scripts only to be able to kill them whenever
      we need it.
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
        self.logger = get_component_logger(self.component)
        sys.stdout = StreamToLogger(self.logger, logging.INFO)
        sys.stderr = StreamToLogger(self.logger, logging.ERROR)
        self.component.value = 'running'
        self.component.save(update_fields=['value'])
        code = self.component.config.get('code')
        if not code:
            self.component.value = 'finished'
            self.component.save(update_fields=['value'])
            return
        print("------START-------")
        try:
            exec(code, globals())
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
        ('watch_alarm_clocks', 30)
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

    def run(self, exit):
        self.exit = exit
        self.logger = get_gw_logger(self.gateway_instance.id)
        for task, period in self.periodic_tasks:
            threading.Thread(
                target=self._run_periodic_task, args=(task, period), daemon=True
            ).start()

        from simo.generic.controllers import Script, IPCamera

        mqtt_client = mqtt.Client()
        mqtt_client.on_connect = self.on_mqtt_connect
        mqtt_client.on_message = self.on_mqtt_message
        mqtt_client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)

        # We presume that this is the only running gateway, therefore
        # if there are any running scripts, that is not true.
        for component in Component.objects.filter(
            controller_uid=Script.uid, value='running'
        ):
            component.value = 'stopped'
            component.save()

        for script in Component.objects.filter(
            controller_uid=Script.uid, config__autostart=True
        ):
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
            self.stop_script(Component.objects.get(id=id))

        while len(script_ids):
            time.sleep(0.1)


    def on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        mqtt_client.subscribe(ObjectCommand.TOPIC)
        mqtt_client.subscribe(Event.TOPIC)

    def on_mqtt_message(self, client, userdata, msg):
        from simo.core.controllers import Switch, BinarySensor
        from simo.generic.controllers import Script, Gate, Blinds
        payload = json.loads(msg.payload)
        component = get_event_obj(payload, Component)
        if not component:
            return


        if msg.topic == ObjectCommand.TOPIC:
            # Handle scripts
            if isinstance(component.controller, Script):
                if payload['kwargs'].get('set_val') == 'start':
                    self.start_script(component)
                elif payload['kwargs'].get('set_val') == 'stop':
                    self.stop_script(component)
                return
            elif component.controller_uid == Blinds.uid:
                self.control_blinds(component, payload['kwargs'].get('set_val'))

        elif msg.topic == Event.TOPIC:
            if isinstance(component.controller, Switch):
                value_change = payload['data'].get('value')
                if not value_change:
                    return

                # Handle Gate switches
                for gate in Component.objects.filter(
                    controller_uid=Gate.uid, config__action_switch=component.id
                ):
                    if gate.config.get('action_method') == 'toggle':
                        gate.controller._set_on_the_move()
                    else:
                        if value_change.get('new') == False:
                            # Button released
                            # set stopped position if it was moving, or set moving if not.
                            if gate.value.endswith('moving'):
                                if gate.config.get('sensor_value'):
                                    gate.set('open')
                                else:
                                    gate.set('closed')
                            else:
                                gate.controller._set_on_the_move()

                return

            elif isinstance(component.controller, BinarySensor):
                value_change = payload['data'].get('value')
                if not value_change:
                    return
                # Handle Gate binary sensors
                for gate in Component.objects.filter(
                    controller_uid=Gate.uid,
                    config__open_closed_sensor=component.id
                ):
                    gate.config['sensor_value'] = component.value
                    gate.save(update_fields=['config'])
                    # If sensor goes from False to True, while gate is moving
                    # it usually means that gate just started the move and must stay in the move
                    # user defined amount of seconds to represent actual gate movement.
                    # Open state therefore is reached only after user defined duration.
                    # If it was not in the move, then it simply means that it was
                    # opened in some other way and we set it to open immediately.
                    if component.value:
                        if gate.value.endswith('moving'):
                            print("SET OPEN MOVING!")
                            gate.set('open_moving')
                        else:
                            gate.set('open')
                    # if binary sensor detects gate close event
                    # we set gate value to closed immediately as it means that
                    # gate is now truly closed and no longer moving.
                    else:
                        gate.set('closed')

    def start_script(self, component):
        print("START SCRIPT %s" % str(component))
        if component.id in self.running_scripts:
            if self.running_scripts[component.id].is_alive():
                return
            # self.running_scripts[component.id].join()
        self.running_scripts[component.id] = ScriptRunHandler(
            component.id, daemon=True
        )
        self.running_scripts[component.id].start()

    def stop_script(self, component):
        if component.id not in self.running_scripts:
            return
        if self.running_scripts[component.id].is_alive():
            logger = get_component_logger(component)
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
                    logger.log(
                        logging.INFO, "-------KILL!-------"
                    )
                    self.running_scripts[component.id].kill()

                component.value = 'stopped'
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




class DummyGatewayHandler(BaseObjectCommandsGatewayHandler):
    name = "Dummy"
    config_form = BaseGatewayForm
