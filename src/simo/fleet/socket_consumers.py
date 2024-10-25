import asyncio
import json
import logging
import pytz
import traceback
import sys
import zlib
from django.db import transaction
from logging.handlers import RotatingFileHandler
from django.utils import timezone
from django.conf import settings
import paho.mqtt.client as mqtt
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from simo.core.utils.model_helpers import get_log_file_path
from simo.core.utils.logs import capture_socket_errors
from simo.core.events import GatewayObjectCommand, get_event_obj
from simo.core.models import Gateway, Instance, Component
from simo.conf import dynamic_settings
from simo.users.models import Fingerprint

from .gateways import FleetGatewayHandler
from .models import Colonel
from .controllers import TTLock


@capture_socket_errors
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
        print("Fleet Socket Connect with headers:", self.scope.get('headers'))
        await self.accept()

        headers = {
            item[0].decode().lower(): item[1].decode() for item in self.scope['headers']
        }

        instance_uid = headers.get('instance-uid')

        def get_instance(instance_uid):
            try:
                return Instance.objects.prefetch_related(
                    'fleet_options'
                ).get(uid=instance_uid)
            except:
                return

        if not instance_uid:
            print("No instance_uid in headers! Disconnect socket!")
            return await self.close()

        self.instance = await sync_to_async(
            get_instance, thread_sensitive=True
        )(instance_uid)

        if not self.instance:
            print("Wrong instance UID!")
            return await self.close()

        if self.instance.fleet_options.secret_key \
            != headers.get('instance-secret'):
            print("Bad instance secret! Headers received: ", headers)
            return await self.close()

        def get_tz():
            return pytz.timezone(self.instance.timezone)

        tz = await sync_to_async(get_tz, thread_sensitive=True)()
        timezone.activate(tz)

        def get_colonel():
            # looks like update_or_create doesn't work in socket/async environment.
            defaults={
                'instance': self.instance,
                'name': headers.get('colonel-name'),
                'type': headers['colonel-type'],
                'firmware_version': headers['firmware-version'],
                'last_seen': timezone.now(),
                'enabled': True
            }
            with transaction.atomic():
                colonel, new = Colonel.objects.get_or_create(
                    uid=headers['colonel-uid'], defaults=defaults
                )
                if not new:
                    for key, val in defaults.items():
                        if key == 'name':
                            continue
                        setattr(colonel, key, val)
                    colonel.save()

            return colonel, new

        self.colonel, new = await sync_to_async(
            get_colonel, thread_sensitive=True
        )()

        print(f"Colonel {self.colonel} connected!")
        if not self.colonel.enabled:
            print("Colonel %s drop, it's not enabled!" % str(self.colonel))
            return await self.close()

        if headers.get('instance-uid') != self.colonel.instance.uid \
        or headers.get('instance-secret') != self.colonel.instance.fleet_options.secret_key:
            print("NOT authorized!")
            return await self.close()

        self.connected = True

        await self.log_colonel_connected()


        def get_gateway():
            return Gateway.objects.filter(
                type=FleetGatewayHandler.uid
            ).first()

        self.gateway = await sync_to_async(
            get_gateway, thread_sensitive=True
        )()

        if self.colonel.firmware_auto_update \
            and self.colonel.minor_upgrade_available:
            await self.firmware_update(self.colonel.minor_upgrade_available)
        else:
            def on_mqtt_connect(mqtt_client, userdata, flags, rc):
                command = GatewayObjectCommand(self.gateway)
                TOPIC = command.get_topic()
                print("SUBSCRIBE TO TOPIC: ", TOPIC)
                mqtt_client.subscribe(TOPIC)

            self.mqtt_client = mqtt.Client()
            self.mqtt_client.username_pw_set('root', settings.SECRET_KEY)
            self.mqtt_client.on_connect = on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.connect(host=settings.MQTT_HOST,
                                     port=settings.MQTT_PORT)
            self.mqtt_client.loop_start()

            # DO NOT FORCE CONFIG DATA!!!!
            # as colonels might already have config and want to
            # send updated values of components, like for example
            # somebody turned some lights on/off while colonel was
            # not connected to the main hub.
            # If we force this, vales get overridden by what is last
            # known by the hub
            # config = await self.get_config_data()
            # await self.send_data(
            #     'command': 'set_config', 'data': config
            # })

            await self.send_data({'command': 'hello'})

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
            await self.send_data({'command': 'ping'})

    async def firmware_update(self, to_version):
        print("Firmware update: ", str(self.colonel))
        await self.send_data({'command': 'ota_update', 'version': to_version})

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

        def get_interfaces(colonel):
            return list(colonel.interfaces.all().select_related(
                'pin_a', 'pin_b'
            ))
        interfaces = await sync_to_async(get_interfaces, thread_sensitive=True)(
            self.colonel
        )
        for interface in interfaces:
            config_data['interfaces'][f'{interface.type}-{interface.no}'] = {
                'pin_a': interface.pin_a.no, 'pin_b': interface.pin_b.no,
            }

        def get_components(colonel):
            return list(
                colonel.components.all().prefetch_related('slaves')
            )
        components = await sync_to_async(
            get_components, thread_sensitive=True
        )(self.colonel)

        def get_comp_config(comp):
            try:
                comp_config = {
                    'type': comp.controller.uid.split('.')[-1],
                    'val': comp.controller._prepare_for_send(
                        comp.value
                    ),
                    'config': comp.controller._get_colonel_config()
                }
                if hasattr(comp.controller, 'family'):
                    comp_config['family'] = comp.controller.family
                slaves = [
                    s.id for s in comp.slaves.all()
                    if s.config.get('colonel') == self.colonel.id
                ]
                if slaves:
                    comp_config['slaves'] = slaves
                if comp.meta.get('options'):
                    comp_config['options'] = comp.meta['options']

                config_data['devices'][str(comp.id)] = comp_config
            except:
                print("Error preparing component config")
                print(traceback.format_exc(), file=sys.stderr)
            else:
                return comp_config

        for component in components:

            comp_config = components = await sync_to_async(
                get_comp_config, thread_sensitive=True
            )(component)

            if not comp_config:
                continue

            slaves = [
                s.id for s in component.slaves.all()
                if s.config.get('colonel') == self.colonel.id
            ]
            if slaves:
                comp_config['slaves'] = slaves
            if component.meta.get('options'):
                comp_config['options'] = component.meta['options']

            config_data['devices'][str(component.id)] = comp_config


        return config_data

    def on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)

            if 'bulk_send' in payload:
                colonel_component_ids = [c['id'] for c in Component.objects.filter(
                    config__colonel=self.colonel.id,
                    gateway__in=Gateway.objects.filter(type=FleetGatewayHandler.uid),
                    id__in=[int(id) for id in payload['bulk_send'].keys()]
                ).values('id')]
                bulk_send_data = []
                for comp_id, value in payload['bulk_send'].items():
                    if int(comp_id) not in colonel_component_ids:
                        continue
                    bulk_send_data.append({'id': int(comp_id), 'val': value})
                if bulk_send_data:
                    asyncio.run(self.send_data({
                        'command': 'bulk_set',
                        'values': bulk_send_data
                    }))
                return

            obj = get_event_obj(payload)

            if obj == self.colonel:
                if payload.get('command') == 'update_firmware':
                    asyncio.run(self.firmware_update(payload['to_version']))
                elif payload.get('command') == 'update_config':
                    async def send_config():
                        config = await self.get_config_data()
                        await self.send_data({
                            'command': 'set_config', 'data': config
                        }, compress=True)
                    asyncio.run(send_config())
                elif payload.get('command') == 'discover':
                    print(f"SEND discover command for {payload['type']}")
                    asyncio.run(self.send_data(payload))

                elif payload.get('command') == 'finalize':
                    asyncio.run(self.send_data({
                        'command': 'finalize',
                        'data': payload.get('data', {})
                    }))
                else:
                    asyncio.run(self.send_data(payload))

            elif isinstance(obj, Component):
                if int(obj.config.get('colonel')) != self.colonel.id:
                    return
                if 'set_val' in payload:
                    asyncio.run(self.send_data({
                        'command': 'set_val',
                        'id': obj.id,
                        'val': payload['set_val']
                    }))
                if 'update_options' in payload:
                    asyncio.run(self.send_data({
                        'command': 'update_options',
                        'id': obj.id,
                        'options': payload['options']
                    }))

        except Exception as e:
            print(traceback.format_exc(), file=sys.stderr)


    async def receive(self, text_data=None, bytes_data=None):
        try:
            if text_data:
                print(f"{self.colonel}: {text_data}")
                data = json.loads(text_data)
                if 'get_config' in data:
                    config = await self.get_config_data()
                    print("Send config: ", config)
                    await self.send_data({
                        'command': 'set_config', 'data': config
                    }, compress=True)
                elif 'comp' in data:
                    try:
                        try:
                            id=int(data['comp'])
                        except:
                            return

                        component = await sync_to_async(
                            Component.objects.get, thread_sensitive=True
                        )(id=id)

                        if 'val' in data:
                            def receive_val(data):
                                if data.get('actor'):
                                    fingerprint = Fingerprint.objects.filter(
                                        value=f"ttlock-{component.id}-{data.get('actor')}",
                                    ).first()
                                    component.change_init_fingerprint = fingerprint
                                component.controller._receive_from_device(
                                    data['val'], bool(data.get('alive')),
                                    data.get('battery_level'), data.get('error_msg')
                                )
                            await sync_to_async(
                                receive_val, thread_sensitive=True
                            )(data)

                        if 'options' in data:
                            def receive_options(val):
                                component.meta['options'] = val
                                component.save()
                            await sync_to_async(
                                receive_options, thread_sensitive=True
                            )(data['options'])

                        if component.controller_uid == TTLock.uid:
                            if 'codes' in data or 'fingerprints' in data:
                                await sync_to_async(
                                    component.controller._receive_meta,
                                    thread_sensitive=True
                                )(data)

                    except Exception as e:
                        print(traceback.format_exc(), file=sys.stderr)

                elif 'discovery-result' in data:
                    def process_discovery_result():
                        self.gateway.refresh_from_db()
                        try:
                            self.gateway.process_discovery(data)
                        except Exception as e:
                            print(traceback.format_exc(), file=sys.stderr)

                    await sync_to_async(
                        process_discovery_result, thread_sensitive=True
                    )()


            elif bytes_data:
                if not self.colonel_logger:
                    await self.start_logger()

                for logline in bytes_data.decode(errors='replace').split('\n'):
                    self.colonel_logger.log(logging.INFO, logline)

            await self.log_colonel_connected()
        except Exception as e:
            print(traceback.format_exc(), file=sys.stderr)



    async def log_colonel_connected(self):

        def save_last_seen():
            self.colonel.socket_connected = True
            self.colonel.last_seen = timezone.now()
            self.colonel.save(update_fields=[
                'socket_connected', 'last_seen',
            ])

        await sync_to_async(save_last_seen, thread_sensitive=True)()

    async def send_data(self, data, compress=False):
        data = json.dumps(data)
        if compress:
            data = zlib.compress(data.encode())
            await self.send(bytes_data=data)
        else:
            await self.send(data)


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



