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
        from simo.fleet.controllers import TTLock
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
            print("Adding door sensor to lock watch!")
            if door_sensor.id in self.door_sensors_on_watch:
                return
            self.door_sensors_on_watch.add(door_sensor.id)
            door_sensor.on_change(self.on_door_sensor)

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
