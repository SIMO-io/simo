import datetime
import time
import json
import threading
from django.utils import timezone
from simo.core.models import Component
from simo.core.gateways import BaseObjectCommandsGatewayHandler
from simo.core.forms import BaseGatewayForm
from simo.core.models import Gateway
from simo.core.events import GatewayObjectCommand, get_event_obj
from simo.core.utils.serialization import deserialize_form_data




class FleetGatewayHandler(BaseObjectCommandsGatewayHandler):
    name = "SIMO.io Fleet"
    config_form = BaseGatewayForm
    info = "Provides components that run on SIMO.io colonel boards " \
           "like The Game Changer"

    periodic_tasks = (
        ('look_for_updates', 600),
        ('watch_colonels_connection', 30),
        ('push_discoveries', 6),
    )

    def run(self, exit):
        from simo.fleet.controllers import TTLock

        self._ensure_button_watch_state()
        self.watch_buttons()


        self.door_sensors_on_watch = set()
        for lock in Component.objects.filter(controller_uid=TTLock.uid):
            if not lock.config.get('door_sensor'):
                continue
            door_sensor = Component.objects.filter(
                id=lock.config['door_sensor']
            ).first()
            if not door_sensor:
                continue
            self.door_sensors_on_watch.add(door_sensor.id)
            door_sensor.on_change(self.on_door_sensor)

        super().run(exit)


    def _on_mqtt_message(self, client, userdata, msg):
        from simo.core.models import Component
        payload = json.loads(msg.payload)
        if payload.get('command') == 'watch_lock_sensor':
            door_sensor = get_event_obj(payload, Component)
            if not door_sensor:
                return
            if door_sensor.id in self.door_sensors_on_watch:
                return
            print("Adding new door sensor to lock watch!")
            self.door_sensors_on_watch.add(door_sensor.id)
            door_sensor.on_change(self.on_door_sensor)
        if payload.get('command') == 'watch_buttons':
            component = get_event_obj(payload, Component)
            if not component:
                return
            self.watch_buttons(component)

    def on_door_sensor(self, sensor):
        from simo.fleet.controllers import TTLock
        for lock in Component.objects.filter(
            controller_uid=TTLock.uid, config__door_sensor=sensor.id
        ):
            lock.check_locked_status()

    def look_for_updates(self):
        from .models import Colonel
        for colonel in Colonel.objects.all():
            colonel.check_for_upgrade()

    def watch_colonels_connection(self):
        from .models import Colonel
        for colonel in Colonel.objects.filter(
            socket_connected=True,
            last_seen__lt=timezone.now() - datetime.timedelta(minutes=2)
        ):
            colonel.socket_connected = False
            colonel.save()

    def push_discoveries(self):
        from .models import Colonel
        for gw in Gateway.objects.filter(
            type=self.uid, discovery__has_key='start',
        ).exclude(discovery__has_key='finished'):
            if time.time() - gw.discovery.get('last_check') > 10:
                gw.finish_discovery()
                continue

            if gw.discovery['controller_uid'] == 'simo.fleet.controllers.TTLock':
                colonel = Colonel.objects.get(
                    id=gw.discovery['init_data']['colonel']['val'][0]['pk']
                )
                GatewayObjectCommand(
                    gw, colonel, command='discover',
                    type=gw.discovery['controller_uid']
                ).publish()
            elif gw.discovery['controller_uid'] == \
            'simo.fleet.controllers.DALIDevice':
                colonel = Colonel.objects.get(
                    id=gw.discovery['init_data']['colonel']['val'][0]['pk']
                )
                form_cleaned_data = deserialize_form_data(gw.discovery['init_data'])
                GatewayObjectCommand(
                    gw, colonel,
                    command=f'discover',
                    type=gw.discovery['controller_uid'],
                    i=form_cleaned_data['interface'].no
                ).publish()
            elif gw.discovery['controller_uid'] == \
            'simo.fleet.controllers.RoomZonePresenceSensor':
                form_cleaned_data = deserialize_form_data(
                    gw.discovery['init_data']
                )
                # Room-zone presence discovery now only supports network sentinels
                colonel = Colonel.objects.filter(
                    id=form_cleaned_data['colonel'].id
                    if hasattr(form_cleaned_data.get('colonel'), 'id')
                    else form_cleaned_data.get('colonel')
                ).first()
                if colonel:
                    GatewayObjectCommand(
                        gw, colonel,
                        command='discover', type=self.uid.split('.')[-1],
                    ).publish()



    def _ensure_button_watch_state(self):
        if not hasattr(self, 'remote_button_watchers'):
            self.remote_button_watchers = {}
        if not hasattr(self, 'remote_button_targets'):
            self.remote_button_targets = {}
        if not hasattr(self, 'remote_button_lock'):
            self.remote_button_lock = threading.RLock()

    @staticmethod
    def _get_control_button_id(ctrl):
        input_id = ctrl.get('input')
        if isinstance(input_id, str) and input_id.startswith('button-'):
            try:
                return int(input_id[7:])
            except (TypeError, ValueError):
                return None

        button_id = ctrl.get('button')
        if button_id in (None, ''):
            return None
        try:
            return int(button_id)
        except (TypeError, ValueError):
            return None

    def _control_matches_button(self, ctrl, button_id):
        return self._get_control_button_id(ctrl) == button_id

    def _get_button_control_components(self):
        from simo.fleet.controllers import (
            Switch, PWMOutput, RGBLight, Blinds, DALIGearGroup, DALILamp
        )

        return Component.objects.filter(
            controller_uid__in=(
                Switch.uid, PWMOutput.uid, RGBLight.uid, Blinds.uid,
                DALIGearGroup.uid, DALILamp.uid
            )
        )

    def _build_remote_button_targets(self):
        button_cache = {}
        current_targets = {}

        for component in self._get_button_control_components():
            for ctrl_no, ctrl in enumerate(component.config.get('controls', [])):
                button_id = self._get_control_button_id(ctrl)
                if button_id is None:
                    continue
                if button_id not in button_cache:
                    button_cache[button_id] = Component.objects.filter(
                        id=button_id
                    ).first()
                button = button_cache[button_id]
                if not button:
                    continue
                if button.config.get('colonel') == component.config.get('colonel'):
                    # button is on a same colonel, therefore colonel handles
                    # all control actions and we do not need to do it here
                    continue
                if button.id not in current_targets:
                    current_targets[button.id] = set()
                current_targets[button.id].add((component.id, ctrl_no))

        return current_targets

    def watch_buttons(self, component=None):
        self._ensure_button_watch_state()
        current_targets = self._build_remote_button_targets()

        with self.remote_button_lock:
            previous_watchers = self.remote_button_watchers
            previous_targets = self.remote_button_targets
            current_watchers = {}

            for button_id in current_targets:
                button = previous_watchers.pop(button_id, None)
                if not button:
                    button = Component.objects.filter(id=button_id).first()
                if not button:
                    continue
                if (
                    button_id not in previous_targets
                    or previous_targets[button_id] != current_targets[button_id]
                ):
                    print(
                        f"Binding button {button} to "
                        f"{len(current_targets[button_id])} fleet control(s)!"
                    )
                button.on_change(self.on_remote_button_change)
                current_watchers[button_id] = button

            for button in previous_watchers.values():
                button.on_change(None)

            self.remote_button_watchers = current_watchers
            self.remote_button_targets = current_targets

    def _dispatch_button_to_component(self, comp, btn, ctrl_no=None):
        controls = comp.config.get('controls', [])
        if ctrl_no is None:
            ctrl_numbers = range(len(controls))
        else:
            ctrl_numbers = [ctrl_no]

        for j in ctrl_numbers:
            if j >= len(controls):
                continue
            ctrl = controls[j]
            if not self._control_matches_button(ctrl, btn.id):
                continue
            if btn.config.get('colonel') == comp.config.get('colonel'):
                return False

            method = ctrl.get('method', 'momentary')
            print(
                f"Button [{j}] {btn}: {btn.value} on {comp} "
                f"| Btn type: {method}"
            )
            comp.controller._ctrl(j, btn.value, method)
            return True

        return False

    def on_remote_button_change(self, btn):
        self._ensure_button_watch_state()
        with self.remote_button_lock:
            raw_targets = self.remote_button_targets.get(btn.id, set())

        if not raw_targets:
            return

        targets = {}
        for component_id, ctrl_no in raw_targets:
            if component_id not in targets or ctrl_no < targets[component_id]:
                targets[component_id] = ctrl_no

        for component_id, ctrl_no in sorted(targets.items()):
            comp = Component.objects.filter(id=component_id).first()
            if not comp:
                continue
            self._dispatch_button_to_component(comp, btn, ctrl_no=ctrl_no)

    def button_action(self, comp, btn):
        comp = Component.objects.filter(id=comp.id).first()
        if not comp:
            return
        self._dispatch_button_to_component(comp, btn)
