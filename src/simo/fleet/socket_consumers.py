import asyncio
import json
import logging
import pytz
import time
from logging.handlers import RotatingFileHandler
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
import paho.mqtt.client as mqtt
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from simo.core.utils.helpers import get_random_string
from simo.core.utils.model_helpers import get_log_file_path
from simo.core.events import ObjectCommand, get_event_obj
from simo.core.utils.helpers import get_self_ip
from simo.core.models import Instance, Component
from simo.conf import dynamic_settings
from .models import Colonel


class FleetConsumer(AsyncWebsocketConsumer):
    colonel = None
    colonel_logger = None
    connected = False
    mqtt_client = None


    async def disconnect(self, code):
        print("Colonel %s socket disconnected!" % str(self.colonel))
        self.connected = False
        if self.mqtt_client:
            self.mqtt_client.loop_stop()

        def save_disconect():
            if self.colonel:
                self.colonel.socket_connected = False
                self.colonel.save(update_fields=['socket_connected'])
        await sync_to_async(save_disconect, thread_sensitive=True)()


    async def connect(self):

        # print("Fleet socket connect! Headers: ", self.scope['headers'])
        headers = {
            item[0].decode(): item[1].decode() for item in self.scope['headers']
        }

        instance_uid = headers.get('instance-uid')

        def get_instance(instance_uid):
            if instance_uid:
                try:
                    return Instance.objects.prefetch_related(
                        'fleet_options'
                    ).get(uid=instance_uid)
                except:
                    return
            # TODO: drop this after all colonels are updated to Instance based architecture
            else:
                return Instance.objects.prefetch_related(
                    'fleet_options'
                ).all().first()

        self.instance = await sync_to_async(
            get_instance, thread_sensitive=True
        )(instance_uid)

        if not self.instance:
            print("Wrong instance UID! Headers received: ", headers)
            return await self.close()

        # TODO: enforce this once all colonels are migrated to INstance based architecture
        # if self.instance.fleet_options.secret_key \
        #     != headers.get('instance-secret'):
        #     print("Bad instance secret! Headers received: ", headers)
        #     return await self.close()

        def get_tz():
            return pytz.timezone(self.instance.timezone)

        tz = await sync_to_async(get_tz, thread_sensitive=True)()
        timezone.activate(tz)

        self.colonel, new = await sync_to_async(
            Colonel.objects.update_or_create, thread_sensitive=True)(
            uid=headers['colonel-uid'], defaults={
                'instance': self.instance,
                'type': headers['colonel-type'],
                'firmware_version': headers['firmware-version'],
                'last_seen': timezone.now()
            }
        )

        print(f"Colonel {self.colonel} connected with headers: {headers}")
        if not self.colonel.enabled:
            print("Colonel %s drop, it's not enabled!" % str(self.colonel))
            await self.accept()
            return await self.close()

        if not self.colonel.name and headers.get('colonel-name'):
            def save_colonel_name(name):
                self.colonel.name = name
                self.colonel.save()

            await sync_to_async(
                save_colonel_name, thread_sensitive=True
            )(headers['colonel-name'])

        def set_colonel_authorized(val):
            self.colonel.is_authorized = val
            self.colonel.save()

        # TODO: replace this to only allow authorized colonels in!
        if headers.get('instance-uid') == self.colonel.instance.uid \
        and headers.get('instance-secret') == self.colonel.instance.fleet_options.secret_key:
            await sync_to_async(
                set_colonel_authorized, thread_sensitive=True
            )(True)
        else:
            await sync_to_async(
                set_colonel_authorized, thread_sensitive=True
            )(False)

        self.connected = True

        await self.accept()

        if self.colonel.firmware_auto_update \
            and self.colonel.minor_upgrade_available:
            await self.firmware_update(self.colonel.minor_upgrade_available)
        else:
            def on_mqtt_connect(mqtt_client, userdata, flags, rc):
                mqtt_client.subscribe(ObjectCommand.TOPIC)

            self.mqtt_client = mqtt.Client()
            self.mqtt_client.on_connect = on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.connect(host=settings.MQTT_HOST,
                                     port=settings.MQTT_PORT)
            self.mqtt_client.loop_start()

            config = await self.get_config_data()
            await self.send(json.dumps({
                'command': 'set_config', 'data': config
            }))

        asyncio.create_task(self.watch_connection())

    async def watch_connection(self):
        while self.connected:
            await sync_to_async(
                self.colonel.refresh_from_db, thread_sensitive=True
            )()

            if self.colonel.firmware_auto_update \
            and self.colonel.minor_upgrade_available:
                await self.firmware_update(
                    self.colonel.minor_upgrade_available
                )

            await asyncio.sleep(10)
            # Default pinging system sometimes get's lost somewhere,
            # therefore we use our own to ensure connection
            await self.send(json.dumps({'command': 'ping'}))

    async def firmware_update(self, to_version):
        print("Firmware update: ", str(self.colonel))
        await self.send(json.dumps({'command': 'ota_update', 'version': to_version}))

    async def get_config_data(self):
        self.colonel = await sync_to_async(
            Colonel.objects.get, thread_sensitive=True
        )(id=self.colonel.id)
        hub_uid = await sync_to_async(
            lambda: dynamic_settings['core__hub_uid'], thread_sensitive=True
        )()

        def get_instance_options():
            return {
                'instance_uid': self.instance.uid,
                'instance_secret': self.instance.fleet_options.secret_key
            }
        instance_options = await sync_to_async(
            get_instance_options, thread_sensitive=True
        )()

        config_data = {
            'devices': {}, 'interfaces': {},
            'settings': {
                'name': self.colonel.name, 'hub_uid': hub_uid,
                'logs_stream': self.colonel.logs_stream,
                'pwm_frequency': self.colonel.pwm_frequency,
            }
        }
        config_data['settings'].update(instance_options)
        i2c_interfaces = await sync_to_async(list, thread_sensitive=True)(
            self.colonel.i2c_interfaces.all()
        )
        for i2c_interface in i2c_interfaces:
            config_data['interfaces']['i2c-%d' % i2c_interface.no] = {
                'scl': i2c_interface.scl_pin, 'sda': i2c_interface.sda_pin,
                'freq': i2c_interface.freq
            }
        components = await sync_to_async(
            list, thread_sensitive=True
        )(self.colonel.components.all())
        for component in components:
            try:
                config_data['devices'][str(component.id)] = {
                    'type': component.controller.uid.split('.')[-1],
                    'config': component.config,
                    'options': component.meta.get('options', {}),
                    'val': component.controller._prepare_for_send(component.value)
                }
            except:
                continue

        return config_data

    def on_mqtt_message(self, client, userdata, msg):
        payload = json.loads(msg.payload)
        colonel = get_event_obj(payload, Colonel)
        if not colonel or colonel != self.colonel:
            return
        if payload['kwargs'].get('command') == 'update_firmware':
            asyncio.run(self.firmware_update(payload['kwargs'].get('to_version')))
        elif payload['kwargs'].get('command') == 'update_config':
            async def send_config():
                config = await self.get_config_data()
                await self.send(json.dumps({
                    'command': 'set_config', 'data': config
                }))
            asyncio.run(send_config())
        else:
            asyncio.run(self.send(json.dumps(payload['kwargs'])))

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            print("[%s]" % str(self.colonel), text_data)
            data = json.loads(text_data)
            if 'get_config' in data:
                config = await self.get_config_data()
                await self.send(json.dumps({
                    'command': 'set_config', 'data': config
                }))
            elif 'comp' in data:
                try:
                    component = await sync_to_async(
                        Component.objects.get, thread_sensitive=True
                    )(id=int(data['comp']))

                    if 'val' in data:
                        def receive_val(val):
                            component.controller._receive_from_device(
                                val, bool(data.get('alive'))
                            )
                        await sync_to_async(
                            receive_val, thread_sensitive=True
                        )(data['val'])

                    if 'options' in data:
                        print("Received options update")
                        def receive_options(val):
                            component.meta['options'] = val
                            component.save()
                        await sync_to_async(
                            receive_options, thread_sensitive=True
                        )(data['options'])

                except Exception as e:
                    print(e)

        elif bytes_data:
            if not self.colonel_logger:
                await self.start_logger()

            for logline in bytes_data.decode(errors='replace').split('\n'):
                self.colonel_logger.log(logging.INFO, logline)

        def save_last_seen():
            self.colonel.socket_connected = True
            self.colonel.last_seen = timezone.now()
            self.colonel.save(update_fields=[
                'socket_connected', 'last_seen',
            ])

        await sync_to_async(save_last_seen, thread_sensitive=True)()


    async def start_logger(self):
        self.colonel_logger = logging.getLogger(
            "Colonel Logger [%d]" % self.colonel.id
        )
        self.colonel_logger.handlers = []
        self.colonel_logger.propagate = False
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            "%m-%d %H:%M:%S"
        )
        formatter.converter = \
            lambda *args, **kwargs: timezone.localtime().timetuple()

        logfile_path = await sync_to_async(
            get_log_file_path, thread_sensitive=True
        )(self.colonel)
        file_handler = RotatingFileHandler(
            logfile_path, maxBytes=1024 * 1024,  # 1Mb
            backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        self.colonel_logger.addHandler(file_handler)



