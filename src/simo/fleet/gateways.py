import datetime
import time
import json
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

    periodic_tasks = (
        ('look_for_updates', 600),
        ('watch_colonels_connection', 30),
        ('push_discoveries', 6),
    )

    def run(self, exit):
        from simo.fleet.controllers import (
            Switch, PWMOutput, RGBLight, Blinds, DALIGearGroup, DALILamp, TTLock
        )

        self.buttons_on_watch = set()
        for component in Component.objects.filter(
            controller_uid__in=(
                Switch.uid, PWMOutput.uid, RGBLight.uid, Blinds.uid,
                DALIGearGroup.uid, DALILamp.uid
            )
        ):
            self.watch_buttons(component)


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

            colonel = Colonel.objects.get(
                id=gw.discovery['init_data']['colonel']['val'][0]['pk']
            )
            if gw.discovery['controller_uid'] == 'simo.fleet.controllers.TTLock':
                GatewayObjectCommand(
                    gw, colonel, command='discover',
                    type=gw.discovery['controller_uid']
                ).publish()
            elif gw.discovery['controller_uid'] == 'simo.fleet.controllers.DALIDevice':
                form_cleaned_data = deserialize_form_data(gw.discovery['init_data'])
                GatewayObjectCommand(
                    gw, colonel,
                    command=f'discover',
                    type=gw.discovery['controller_uid'],
                    i=form_cleaned_data['interface'].no
                ).publish()

    def watch_buttons(self, component):
        for i, ctrl in enumerate(component.config.get('controls', [])):
            if not ctrl.get('input', '').startswith('button'):
                continue
            button = Component.objects.filter(id=ctrl['input'][7:]).first()
            if not button:
                continue
            if button.id in self.buttons_on_watch:
                continue
            if button.config.get('colonel') == component.config.get('colonel'):
                # button is on a same colonel, therefore colonel handles
                # all control actions and we do not need to do it here
                continue

            def button_action(btn):
                self.button_action(component, btn)
            print(f"Binding button {button} to {component}!")
            button.on_change(button_action)
            self.buttons_on_watch.add(button.id)

    def button_action(self, comp, btn):
        comp.refresh_from_db()
        for j, ctrl in enumerate(comp.config.get('controls', [])):
            if ctrl['input'] == f'button-{btn.id}':
                method = ctrl.get('method', 'momentary')
                print(
                    f"Button [{j}] {btn}: {btn.value} on {comp} "
                    f"| Btn type: {method}"
                )
                comp.controller._ctrl(j, btn.value, method)
                break