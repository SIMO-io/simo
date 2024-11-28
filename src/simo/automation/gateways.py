import os
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
        try:
            tz = pytz.timezone(self.component.zone.instance.timezone)
        except:
            tz = pytz.timezone('UTC')
        timezone.activate(tz)
        introduce_instance(self.component.zone.instance)
        self.logger = get_component_logger(self.component)
        sys.stdout = StreamToLogger(self.logger, logging.INFO)
        sys.stderr = StreamToLogger(self.logger, logging.ERROR)
        self.component.meta['pid'] = os.getpid()
        self.component.set('running')

        if hasattr(self.component.controller, '_run'):
            def run_code():
                self.component.controller._run()
        else:
            code = self.component.config.get('code')
            def run_code():
                start = time.time()
                exec(code, globals())
                if 'class Automation:' in code and time.time() - start < 1:
                    Automation().run()

            if not code:
                self.component.value = 'finished'
                self.component.save(update_fields=['value'])
                return
        print("------START-------")
        try:
            run_code()
        except:
            print("------ERROR------")
            self.component.set('error')
            raise
        else:
            print("------FINISH-----")
            self.component.set('finished')
            return


class AutomationsGatewayHandler(BaseObjectCommandsGatewayHandler):
    name = "Automation"
    config_form = BaseGatewayForm

    running_scripts = {}
    periodic_tasks = (
        ('watch_scripts', 10),
    )

    terminating_scripts = set()


    def watch_scripts(self):
        drop_current_instance()
        # observe running scripts and drop the ones that are no longer alive
        dead_scripts = False
        for id, process in list(self.running_scripts.items()):
            comp = Component.objects.filter(id=id).first()
            if process.is_alive():
                if not comp and id not in self.terminating_scripts:
                    # script is deleted, or instance deactivated
                    process.kill()
                continue
            else:
                if id not in self.terminating_scripts:
                    dead_scripts = True
                    if comp:
                        logger = get_component_logger(comp)
                        logger.log(logging.INFO, "-------DEAD!-------")
                    self.stop_script(comp, 'error')

        if dead_scripts:
            # give 10s air before we wake these dead scripts up!
            return

        from .controllers import Script
        for script in Component.objects.filter(
            controller_uid=Script.uid,
            config__keep_alive=True
        ).exclude(value__in=('running', 'stopped', 'finished')):
            self.start_script(script)

    def run(self, exit):
        drop_current_instance()
        self.exit = exit
        self.logger = get_gw_logger(self.gateway_instance.id)
        for task, period in self.periodic_tasks:
            threading.Thread(
                target=self._run_periodic_task, args=(exit, task, period), daemon=True
            ).start()

        from .controllers import Script

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
        # as well as those that are designed to be kept alive, but
        # got terminated unexpectedly
        for script in Component.objects.filter(
            base_type='script',
        ).filter(
            Q(config__autostart=True) |
            Q(value='error', config__keep_alive=True)
        ).distinct():
            self.start_script(script)

        print("GATEWAY STARTED!")
        while not exit.is_set():
            mqtt_client.loop()
        mqtt_client.disconnect()

        script_ids = [id for id in self.running_scripts.keys()]
        for id in script_ids:
            self.stop_script(
                Component.objects.get(id=id), 'error'
            )

        time.sleep(0.5)
        while len(self.running_scripts.keys()):
            print("Still running scripts: ", self.running_scripts.keys())
            time.sleep(0.5)

    def on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        command = GatewayObjectCommand(self.gateway_instance)
        mqtt_client.subscribe(command.get_topic())

    def on_mqtt_message(self, client, userdata, msg):
        print("Mqtt message: ", msg.payload)
        from .controllers import Script
        payload = json.loads(msg.payload)
        drop_current_instance()
        component = get_event_obj(payload, Component)
        if not component:
            return
        introduce_instance(component.zone.instance)
        if not isinstance(component.controller, Script):
            return

        if payload.get('set_val') == 'start':
            self.start_script(component)
        elif payload.get('set_val') == 'stop':
            self.stop_script(component)


    def start_script(self, component):
        print("START SCRIPT %s" % str(component))
        if component.id in self.running_scripts:
            if component.id not in self.terminating_scripts:
                if component.value != 'running':
                    component.value = 'running'
                    component.save()
                    return
            else:
                good_to_go = False
                for i in range(12): # wait for 3s
                    time.sleep(0.2)
                    component.refresh_from_db()
                    if component.id not in self.running_scripts:
                        good_to_go = True
                        break
                if not good_to_go:
                    return self.stop_script(component, 'error')

        self.running_scripts[component.id] = ScriptRunHandler(
            component.id, daemon=True
        )
        self.running_scripts[component.id].start()

    def stop_script(self, component, stop_status='stopped'):
        self.terminating_scripts.add(component.id)
        if component.id not in self.running_scripts:
            if component.value == 'running':
                component.value = stop_status
                component.save(update_fields=['value'])
            return

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

            component.set(stop_status)
            self.terminating_scripts.remove(component.id)
            # making sure it's fully killed along with it's child processes
            self.running_scripts[component.id].kill()
            self.running_scripts.pop(component.id, None)
            logger.handlers = []

        threading.Thread(target=kill, daemon=True).start()