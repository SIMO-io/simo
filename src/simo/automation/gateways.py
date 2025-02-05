import os
import sys
import logging
import pytz
import json
import time
import multiprocessing
import threading
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
from simo.core.utils.converters import input_to_meters
from simo.core.events import GatewayObjectCommand, get_event_obj
from simo.core.loggers import get_gw_logger, get_component_logger
from simo.users.models import InstanceUser
from .helpers import haversine_distance


class ScriptRunHandler(multiprocessing.Process):
    '''
      Threading offers better overall stability, but we use
      multiprocessing for Scripts so that they are better isolated and
      we are able to kill them whenever we need.
    '''
    component = None
    logger = None

    def __init__(self, component_id, exit_event, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.component_id = component_id
        self.exit_event = exit_event
        self.exit_in_use = multiprocessing.Event()
        self.exin_in_use_fail = multiprocessing.Event()

    def run(self):
        db_connection.connect()
        self.component = Component.objects.get(id=self.component_id)
        tz = pytz.timezone(self.component.zone.instance.timezone)
        timezone.activate(tz)
        introduce_instance(self.component.zone.instance)
        self.logger = get_component_logger(self.component)
        sys.stdout = StreamToLogger(self.logger, logging.INFO)
        sys.stderr = StreamToLogger(self.logger, logging.ERROR)
        self.component.meta['pid'] = os.getpid()
        self.component.set('running')
        print("------START-------")
        try:
            self.run_code()
        except:
            print("------ERROR------")
            self.component.set('error')
            raise
        else:
            if not self.exit_event.is_set():
                print("------FINISH-----")
                self.component.set('finished')
            return

    def run_code(self):
        if hasattr(self.component.controller, '_run'):
            self.component.controller._run()
        else:
            code = self.component.config.get('code')
            if not code:
                self.component.value = 'finished'
                self.component.save(update_fields=['value'])
                return
            start = time.time()
            namespace = {}
            exec(code, namespace)
            if 'Automation' in namespace and time.time() - start < 1:
                self.exit_in_use.set()
                try:
                    namespace['Automation']().run(self.exit_event)
                except:
                    self.exin_in_use_fail.set()
                    namespace['Automation']().run()



class GatesHandler:
    '''
      Handles automatic gates openning
    '''
    # users are considered out of gate geofence, when they
    # go out at least this amount of meters away from the gate
    GEOFENCE_CROSS_ZONE = 200

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate_iusers = {}

    def _is_out_of_geofence(self, gate, location):
        '''
        Returns True if given location is out of geofencing zone
        '''

        auto_open_distance = gate.config.get('auto_open_distance')
        if not auto_open_distance:
            return False
        auto_open_distance = input_to_meters(auto_open_distance)

        gate_location = gate.config.get('location')
        try:
            distance_meters = haversine_distance(
                gate_location,
                location, units_of_measure='metric'
            )
        except:
            gate_location = gate.zone.instance.location
            try:
                distance_meters = haversine_distance(
                    gate_location,
                    location, units_of_measure='metric'
                )
            except:
                print(f"Bad location of {gate}!")
                return False
        print(f"Distance from {gate} : {distance_meters}m")
        return distance_meters > (
            auto_open_distance + self.GEOFENCE_CROSS_ZONE
        )

    def _is_in_geofence(self, gate, location):
        '''
        Returns True if given location is within geofencing zone
        '''
        auto_open_distance = gate.config.get('auto_open_distance')
        if not auto_open_distance:
            return False
        auto_open_distance = input_to_meters(auto_open_distance)
        gate_location = gate.config.get('location')
        try:
            distance_meters = haversine_distance(
                gate_location,
                location, units_of_measure='metric'
            )
        except:
            gate_location = gate.zone.instance.location
            try:
                distance_meters = haversine_distance(
                    gate_location,
                    location, units_of_measure='metric'
                )
            except:
                print(f"Bad location of {gate}!")
                return False

        print(f"Distance from {gate} : {distance_meters}m")
        return distance_meters <= auto_open_distance

    def check_gates(self, iuser):
        if not iuser.last_seen_location:
            print("User's last seen location is unknown")
            return
        for gate_id, geofence_data in self.gate_iusers.items():
            for iu_id, is_out in geofence_data.items():
                if iu_id != iuser.id:
                    continue
                gate = Component.objects.get(id=gate_id)
                if is_out:
                    print(
                        f"{iuser.user.name} is out, "
                        f"let's see if we must open the gates for him"
                    )
                    # user was fully out, we must check if
                    # he is now coming back and open the gate for him
                    if self._is_in_geofence(gate, iuser.last_seen_location):
                        print("Yes he is back in a geofence! Open THE GATEEE!!")
                        self.gate_iusers[gate_id][iuser.id] = False
                        gate.open()
                    else:
                        print("No he is not back yet.")
                else:
                    print(f"Check if {iuser.user.name} is out.")
                    self.gate_iusers[gate_id][iuser.id] = self._is_out_of_geofence(
                        gate, iuser.last_seen_location
                    )
                    if self.gate_iusers[gate_id][iuser.id]:
                        print(f"YES {iuser.user.name} is out!")

    def watch_gates(self):
        drop_current_instance()
        for gate in Component.objects.filter(base_type='gate').select_related(
            'zone', 'zone__instance'
        ):
            if not gate.config.get('auto_open_distance'):
                continue
            # Track new users as they appear in the system
            for iuser in InstanceUser.objects.filter(
                is_active=True, instance=gate.zone.instance
            ):
                if gate.config.get('auto_open_for'):
                    if iuser.role.id not in gate.config['auto_open_for']:
                        continue
                if gate.id not in self.gate_iusers:
                    self.gate_iusers[gate.id] = {}
                if iuser.id not in self.gate_iusers[gate.id]:
                    if iuser.last_seen_location:
                        self.gate_iusers[gate.id][iuser.id] = self._is_out_of_geofence(
                            gate, iuser.last_seen_location
                        )
                    iuser.on_change(self.check_gates)


class AutomationsGatewayHandler(GatesHandler, BaseObjectCommandsGatewayHandler):
    name = "Automation"
    config_form = BaseGatewayForm
    info = "Provides various types of automation capabilities"

    running_scripts = {}
    periodic_tasks = (
        ('watch_scripts', 10),
        ('watch_gates', 60)
    )

    terminating_scripts = set()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_death = 0


    def watch_scripts(self):
        drop_current_instance()
        # observe running scripts and drop the ones that are no longer alive
        for id, data in list(self.running_scripts.items()):
            if time.time() - data['start_time'] < 5:
                continue
            process = data['proc']

            comp = Component.objects.filter(id=id).first()
            if comp and comp.value == 'finished':
                if process.is_alive():
                    process.kill()
                self.running_scripts.pop(id)
                continue

            if process.is_alive():
                if not comp and id not in self.terminating_scripts:
                    # script is deleted and was not properly called to stop
                    process.kill()
                    self.running_scripts.pop(id)
                continue
            else:
                # it as been observed that is_alive might sometimes report false
                # however the process is actually still running
                process.kill()
                self.last_death = time.time()
                self.running_scripts.pop(id, None) # no longer running for sure!
                if not comp or comp.value != 'running':
                    continue

                if id not in self.terminating_scripts: # was not intentionaly terminated
                    if comp:
                        tz = pytz.timezone(comp.zone.instance.timezone)
                        timezone.activate(tz)
                    logger = get_component_logger(comp)
                    logger.log(logging.INFO, "-------DEAD!-------")
                    comp.value = 'error'
                    comp.save()

        if self.last_death and time.time() - self.last_death < 5:
            # give 10s air before we wake these dead scripts up!
            return

        for script in Component.objects.filter(
            base_type='script', config__keep_alive=True
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
            # it appears that the script is running and is perfectly healthy
            # so we make sure it has correct value, do nothing else and return!
            if component.id not in self.terminating_scripts \
            and self.running_scripts[component.id]['proc'].is_alive():
                if component.value != 'running':
                    component.value = 'running'
                    component.save()
                return

            # script is in terminating state or is no longer alive
            # since starting of a new script was requested, we kill it viciously
            # and continue on!
            try:
                self.running_scripts[component.id]['proc'].kill()
            except:
                pass
            self.running_scripts.pop(component.id, None)


        process = ScriptRunHandler(
            component.id, multiprocessing.Event(), daemon=True
        )
        process.start()
        self.running_scripts[component.id] = {
            'proc': process, 'start_time': time.time()
        }


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
        elif stop_status == 'stopped':
            logger.log(logging.INFO, "-------STOP-------")

        if self.running_scripts[component.id]['proc'].exit_in_use.is_set()\
        and not self.running_scripts[component.id]['proc'].exin_in_use_fail.is_set():
            self.running_scripts[component.id]['proc'].exit_event.set()
        else:
            self.running_scripts[component.id]['proc'].terminate()

        def kill():
            start = time.time()
            terminated = False
            while start > time.time() - 2:
                if not self.running_scripts[component.id]['proc'].is_alive():
                    terminated = True
                    break
                time.sleep(0.1)
            if not terminated:
                if stop_status == 'error':
                    logger.log(logging.INFO, "-------GATEWAY KILL-------")
                else:
                    logger.log(logging.INFO, "-------KILL!-------")
                self.running_scripts[component.id]['proc'].kill()

            component.set(stop_status)
            self.terminating_scripts.remove(component.id)
            # making sure it's fully killed along with it's child processes
            self.running_scripts[component.id]['proc'].kill()
            self.running_scripts.pop(component.id, None)
            logger.handlers = []

        threading.Thread(target=kill, daemon=True).start()