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
from simo.core.events import (
    GatewayObjectCommand, get_event_obj,
    set_current_watcher_stop_event, clear_current_watcher_stop_event,
    cleanup_watchers_for_event
)
from simo.core.loggers import get_gw_logger, get_component_logger
from simo.users.models import InstanceUser
from .helpers import haversine_distance
from simo.core.utils.mqtt import connect_with_retry, install_reconnect_handler


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
        self.watchers_cleaned = multiprocessing.Event()

    def run(self):
        db_connection.connect()
        self.component = Component.objects.get(id=self.component_id)
        tz = pytz.timezone(self.component.zone.instance.timezone)
        timezone.activate(tz)
        introduce_instance(self.component.zone.instance)
        self.logger = get_component_logger(self.component)

        original_stdout, original_stderr = sys.stdout, sys.stderr
        stdout_logger = StreamToLogger(self.logger, logging.INFO)
        stderr_logger = StreamToLogger(self.logger, logging.ERROR)
        sys.stdout = stdout_logger
        sys.stderr = stderr_logger
        self.component.meta['pid'] = os.getpid()
        self.component.set('running')
        print("------START-------")
        try:
            set_current_watcher_stop_event(self.exit_event)
            def _await_exit_cleanup():
                try:
                    self.exit_event.wait()
                except Exception:
                    pass
                finally:
                    try:
                        cleanup_watchers_for_event(self.exit_event)
                    finally:
                        self.watchers_cleaned.set()

            threading.Thread(
                target=_await_exit_cleanup, daemon=True
            ).start()
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
        finally:
            cleanup_watchers_for_event(self.exit_event)
            clear_current_watcher_stop_event()
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            self.watchers_cleaned.set()

    def run_code(self):
        controller = self.component.controller
        if hasattr(controller, '_run'):
            # Allow scripts implemented via `_run` to receive cooperative
            # shutdown signals instead of being force-killed.
            self.exit_in_use.set()
            controller.exit_event = self.exit_event
            controller._run()
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

    def _log(self, level, message):
        logger = getattr(self, 'logger', None)
        if logger:
            logger.log(level, message)
        else:
            print(message)

    def _log_info(self, message):
        self._log(logging.INFO, message)

    def _log_warning(self, message):
        self._log(logging.WARNING, message)

    def _log_debug(self, message):
        self._log(logging.DEBUG, message)

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
                self._log_warning(f"Bad location of {gate}!")
                return False
        self._log_info(f"Distance from {gate} : {distance_meters}m")
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
                self._log_warning(f"Bad location of {gate}!")
                return False

        self._log_info(f"Distance from {gate} : {distance_meters}m")
        return distance_meters <= auto_open_distance

    def check_gates(self, iuser):
        if not iuser.last_seen_location:
            self._log_warning("User's last seen location is unknown")
            return
        for gate_id, geofence_data in self.gate_iusers.items():
            for iu_id, is_out in geofence_data.items():
                if iu_id != iuser.id:
                    continue
                gate = Component.objects.get(id=gate_id)
                if is_out > 4:
                    self._log_info(
                        f"{iuser.user.name} is out, let's see if we must open the gates for him"
                    )
                    # user was fully out, we must check if
                    # he is now coming back and open the gate for him
                    if self._is_in_geofence(gate, iuser.last_seen_location):
                        self._log_info("Yes he is back in a geofence! Open THE GATEEE!!")
                        self.gate_iusers[gate_id][iuser.id] = 0
                        if iuser.last_seen_speed_kmh > 10:
                            gate.open()
                    else:
                        self._log_info("No he is not back yet.")
                else:
                    self._log_info(f"Check if {iuser.user.name} is out.")
                    if self._is_out_of_geofence(gate, iuser.last_seen_location):
                        self.gate_iusers[gate_id][iuser.id] += 1
                    if self.gate_iusers[gate_id][iuser.id] > 4:
                        self._log_info(f"YES {iuser.user.name} is truly out!")

    def watch_gates(self):
        drop_current_instance()
        for gate in Component.objects.filter(base_type='gate').select_related(
            'zone', 'zone__instance'
        ):
            if not gate.config.get('auto_open_distance'):
                continue
            # Track new users as they appear in the system
            for iuser in InstanceUser.objects.filter(
                is_active=True, instance=gate.zone.instance,
                role__is_person=True
            ):
                if gate.config.get('auto_open_for'):
                    if iuser.role.id not in gate.config['auto_open_for']:
                        continue
                if gate.id not in self.gate_iusers:
                    self.gate_iusers[gate.id] = {}
                if iuser.id not in self.gate_iusers[gate.id]:
                    if iuser.last_seen_location:
                        self.gate_iusers[gate.id][iuser.id] = 0
                        if self._is_out_of_geofence(
                            gate, iuser.last_seen_location
                        ):
                            self.gate_iusers[gate.id][iuser.id] += 1
                    iuser.on_change(self.check_gates)


class AutomationsGatewayHandler(GatesHandler, BaseObjectCommandsGatewayHandler):
    name = "Automation"
    config_form = BaseGatewayForm
    auto_create = True
    info = "Provides various types of automation capabilities"

    running_scripts = None
    periodic_tasks = (
        ('watch_scripts', 10),
        ('watch_gates', 60)
    )

    terminating_scripts = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_death = 0
        self._scripts_lock = threading.RLock()
        self.running_scripts = {}
        self.terminating_scripts = set()


    def watch_scripts(self):
        drop_current_instance()
        with self._scripts_lock:
            running_snapshot = list(self.running_scripts.items())

        # observe running scripts and drop the ones that are no longer alive
        for id, data in running_snapshot:
            if time.time() - data['start_time'] < 5:
                continue
            process = data['proc']

            comp = Component.objects.filter(id=id).first()
            if comp and comp.value == 'finished':
                if process.is_alive():
                    process.kill()
                with self._scripts_lock:
                    self.running_scripts.pop(id, None)
                continue

            with self._scripts_lock:
                terminating = id in self.terminating_scripts

            if process.is_alive():
                if not comp and not terminating:
                    # script is deleted and was not properly called to stop
                    process.kill()
                    with self._scripts_lock:
                        self.running_scripts.pop(id, None)
                continue

            # it has been observed that is_alive might sometimes report false
            # however the process is actually still running
            process.kill()
            self.last_death = time.time()
            # If component exists and is marked running, attempt to persist error
            # BEFORE removing from in-memory tracking, so we can retry if DB is down.
            if comp and comp.value == 'running' and not terminating:
                try:
                    tz = pytz.timezone(comp.zone.instance.timezone)
                    timezone.activate(tz)
                    logger = get_component_logger(comp)
                    logger.log(logging.INFO, "-------DEAD!-------")
                    comp.value = 'error'
                    comp.save()
                except Exception:
                    # Leave entry in running_scripts to retry on next tick
                    continue
            # For any other case or after successful DB update, drop tracking entry
            with self._scripts_lock:
                self.running_scripts.pop(id, None)

        if self.last_death and time.time() - self.last_death < 5:
            # give 10s air before we wake these dead scripts up!
            return

        # Reconcile scripts marked as 'running' in DB but not tracked or with dead PID
        with self._scripts_lock:
            tracked_ids = set(self.running_scripts.keys())
        for comp in Component.objects.filter(base_type='script', value='running'):
            if comp.id in tracked_ids:
                continue
            pid = None
            try:
                pid = int(comp.meta.get('pid')) if comp.meta and 'pid' in comp.meta else None
            except Exception:
                pid = None
            is_pid_alive = bool(pid) and os.path.exists(f"/proc/{pid}")
            if not is_pid_alive:
                try:
                    comp.value = 'error'
                    comp.save(update_fields=['value'])
                except Exception:
                    pass

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

        self.mqtt_client = mqtt.Client()
        self.mqtt_client.username_pw_set('root', settings.SECRET_KEY)
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_message = self.on_mqtt_message
        try:
            self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)
        except Exception:
            pass

        install_reconnect_handler(
            self.mqtt_client,
            logger=self.logger,
            stop_event=self.exit,
            description='Automations gateway MQTT',
        )
        if not connect_with_retry(
            self.mqtt_client,
            logger=self.logger,
            stop_event=self.exit,
            description='Automations gateway MQTT',
        ):
            return

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
        self.mqtt_client.loop_start()
        while not exit.is_set():
            time.sleep(1)
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

        with self._scripts_lock:
            script_ids = list(self.running_scripts.keys())
        for id in script_ids:
            self.stop_script(
                Component.objects.get(id=id), 'error'
            )

        time.sleep(0.5)
        while True:
            with self._scripts_lock:
                remaining = list(self.running_scripts.keys())
            if not remaining:
                break
            self._log_info(
                f"Still running scripts: {remaining}"
            )
            time.sleep(0.5)

    def on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        command = GatewayObjectCommand(self.gateway_instance)
        mqtt_client.subscribe(command.get_topic())

    def on_mqtt_message(self, client, userdata, msg):
        self._log_debug(f"Mqtt message: {msg.payload}")
        from .controllers import Script
        from simo.users.models import User
        from simo.users.utils import introduce_user

        payload = json.loads(msg.payload)
        actor_id = payload.get('actor_id')
        if actor_id:
            try:
                user = User.objects.get(pk=actor_id)
                introduce_user(user)
            except Exception:
                pass
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
        self._log_info(f"START SCRIPT {component}")

        with self._scripts_lock:
            entry = self.running_scripts.get(component.id)
            if entry:
                proc = entry['proc']
                # Script appears to be healthy; do nothing and return.
                if component.id not in self.terminating_scripts and proc.is_alive():
                    return

                # script is in terminating state or is no longer alive
                # since starting of a new script was requested, we kill it viciously
                # and continue on!
                try:
                    proc.kill()
                except Exception:
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
        with self._scripts_lock:
            self.terminating_scripts.add(component.id)
            script_entry = self.running_scripts.get(component.id)
        if not script_entry:
            if component.value == 'running':
                component.value = stop_status
                component.save(update_fields=['value'])
            with self._scripts_lock:
                self.terminating_scripts.discard(component.id)
            return

        tz = pytz.timezone(component.zone.instance.timezone)
        timezone.activate(tz)
        logger = get_component_logger(component)
        if stop_status == 'error':
            logger.log(logging.INFO, "-------GATEWAY STOP-------")
        elif stop_status == 'stopped':
            logger.log(logging.INFO, "-------STOP-------")

        script_proc = script_entry['proc']
        cooperative_exit = script_proc.exit_in_use.is_set() and not script_proc.exin_in_use_fail.is_set()
        script_proc.exit_event.set()

        def kill():
            if not cooperative_exit:
                watchers_cleaned = getattr(script_proc, 'watchers_cleaned', None)
                if watchers_cleaned is not None:
                    try:
                        watchers_cleaned.wait(timeout=2)
                    except Exception:
                        pass
                if script_proc.is_alive():
                    script_proc.terminate()
            start = time.time()
            terminated = False
            while start > time.time() - 2:
                if not script_proc.is_alive():
                    terminated = True
                    break
                time.sleep(0.1)
            if not terminated:
                if stop_status == 'error':
                    logger.log(logging.INFO, "-------GATEWAY KILL-------")
                else:
                    logger.log(logging.INFO, "-------KILL!-------")
                script_proc.kill()

            component.set(stop_status)
            with self._scripts_lock:
                self.terminating_scripts.discard(component.id)
                # making sure it's fully killed along with it's child processes
                script_proc.kill()
                self.running_scripts.pop(component.id, None)
            logger.handlers = []

        threading.Thread(target=kill, daemon=True).start()
