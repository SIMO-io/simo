import json
import asyncio
from ansi2html import Ansi2HTMLConverter
from asgiref.sync import sync_to_async
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from channels.generic.websocket import AsyncWebsocketConsumer, WebsocketConsumer
from simo.core.events import ObjectChangeEvent, get_event_obj
from simo.core.utils.logs import capture_socket_errors
import paho.mqtt.client as mqtt
from simo.users.middleware import introduce
from simo.core.models import Component, Gateway
from simo.core.utils.model_helpers import get_log_file_path
from simo.core.middleware import introduce_instance


@capture_socket_errors
class SIMOWebsocketConsumer(WebsocketConsumer):
    headers = {}

    def accept(self, subprotocol=None):
        super().accept(subprotocol=subprotocol)
        self.headers = {
            key.decode(): val.decode() for key, val in self.scope['headers']
        }


@capture_socket_errors
class LogConsumer(AsyncWebsocketConsumer):
    log_file = None
    in_error = False
    watch = True

    async def connect(self):
        obj_type = await sync_to_async(
            ContentType.objects.get, thread_sensitive=True
        )(id=self.scope['url_route']['kwargs']['ct_id'])
        self.obj = await sync_to_async(
            obj_type.get_object_for_this_type, thread_sensitive=True
        )(
            pk=self.scope['url_route']['kwargs']['object_pk'],
        )
        introduce(self.scope['user'])
        await self.accept()

        if not self.scope['user'].is_authenticated:
            return self.close()

        def get_is_active():
            return self.scope['user'].is_active
        is_active = await sync_to_async(
            get_is_active, thread_sensitive=True
        )()
        if not is_active:
            return self.close()

        def get_role():
            instance = None
            if isinstance(self.obj, Component):
                instance = self.obj.zone.instance
            if not instance:
                # in case it's an opbjec of some other type like fleet.Colonel
                instance = getattr(self.obj, 'instance', None)
            return self.scope['user'].get_role(instance)

        if not self.scope['user'].is_master:
            role = await sync_to_async(
                get_role, thread_sensitive=True
            )()
            if not role or not role.is_superuser:
                return self.close()

        self.log_file_path = get_log_file_path(self.obj)
        self.log_file = open(self.log_file_path)
        lines = [l.rstrip('\n') for l in self.log_file]

        self.ansi_converter = Ansi2HTMLConverter()

        for i, line in enumerate(lines):
            line = self.ansi_converter.convert(line, full=False)
            if '[ERROR]' in line:
                if not self.in_error:
                    self.in_error = True
                    lines[i] = '<div class="code-error">' + line
                else:
                    lines[i] = line
            elif '[INFO]' in line:
                if self.in_error:
                    lines[i] = '</div>' + line
                    self.in_error = False
                else:
                    lines[i] = line
            else:
                lines[i] = line
        if self.in_error:
            lines[-1] = '</div>' + lines[-1]

        await self.send(text_data=('<br>'.join(lines[-500:])))

        asyncio.create_task(self.watch_log_file())

    async def watch_log_file(self):
        while self.watch:
            try:
                line = self.log_file.readline()
            except:
                self.log_file_path = get_log_file_path(self.obj)
                self.log_file = open(self.log_file_path)
                continue
            if not line:
                await asyncio.sleep(0.3)
                continue
            line = self.ansi_converter.convert(line, full=False)
            if '[ERROR]' in line:
                self.in_error = True
                line = '<div class="code-error">%s</div>' % line
            else:
                line = '<br>' + line
                self.in_error = False
            await self.send(text_data=line)

    async def disconnect(self, code):
        if self.log_file:
            self.log_file.close()
            self.log_file = None


@capture_socket_errors
class GatewayController(SIMOWebsocketConsumer):
    gateway = None
    _mqtt_client = None

    def connect(self):

        introduce(self.scope['user'])

        self.gateway = Gateway.objects.get(
            pk=self.scope['url_route']['kwargs']['gateway_id']
        )
        self.accept()

        if not self.scope['user'].is_authenticated:
            return self.close()
        if not self.scope['user'].is_active:
            return self.close()
        if not self.scope['user'].is_superuser:
            return self.close()

        self._mqtt_client = mqtt.Client()
        self._mqtt_client.username_pw_set('root', settings.SECRET_KEY)
        self._mqtt_client.on_connect = self._on_mqtt_connect
        self._mqtt_client.on_message = self._on_mqtt_message
        self._mqtt_client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
        self._mqtt_client.loop_start()

    def _on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        mqtt_client.subscribe(
            f'{ObjectChangeEvent.TOPIC}/global/Gateway-{self.gateway.id}'
        )

    def _on_mqtt_message(self, mqtt_client, userdata, msg):
        payload = json.loads(msg.payload)
        gateway = get_event_obj(payload, Gateway)
        if gateway == self.gateway:
            self.gateway = gateway
            self.send(text_data=render_to_string(
                'admin/gateway_control/widget_internals.html', {'obj': gateway}
            ))

    def receive(self, text_data=None, bytes_data=None, **kwargs):
        json_data = json.loads(text_data)
        for method, params in json_data.items():
            getattr(self.gateway, method)(**params)

    def disconnect(self, console_log):
        if self._mqtt_client:
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except:
                pass


@capture_socket_errors
class ComponentController(SIMOWebsocketConsumer):
    component = None
    send_value = False
    _mqtt_client = None

    def connect(self):

        introduce(self.scope['user'])
        self.accept()

        try:
            self.component = Component.objects.get(
                pk=self.scope['url_route']['kwargs']['component_id']
            )
        except:
            return self.close()

        if not self.component.controller.admin_widget_template:
            return self.close()

        if not self.scope['user'].is_authenticated:
            print("DROPPING SOCKET AS NOT AUTHENTICATED")
            self.send(text_data=json.dumps(
                {'event': 'close', 'reason': 'auth'}
            ))
            return self.close()

        if not self.scope['user'].is_active:
            return self.close()

        introduce_instance(self.component.zone.instance)

        self._mqtt_client = mqtt.Client()
        self._mqtt_client.username_pw_set('root', settings.SECRET_KEY)
        self._mqtt_client.on_connect = self._on_mqtt_connect
        self._mqtt_client.on_message = self._on_mqtt_message
        self._mqtt_client.connect(host=settings.MQTT_HOST,
                                 port=settings.MQTT_PORT)
        self._mqtt_client.loop_start()

    def _on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        print("Subscribing to ComponentEvent's")
        event = ObjectChangeEvent(self.component.zone.instance, self.component)
        mqtt_client.subscribe(event.get_topic())

    def _on_mqtt_message(self, mqtt_client, userdata, msg):
        payload = json.loads(msg.payload)
        component = get_event_obj(payload, Component)
        if component == self.component:
            introduce_instance(self.component.zone.instance)
            # print("Object changed [%s], %s" % (str(component), payload))
            self.component = component
            if self.send_value:
                self.send(
                    text_data=json.dumps(
                        {'value': self.component.value}
                    )
                )
            else:
                self.send(text_data=render_to_string(
                    self.component.controller.admin_widget_template,
                    {'obj': self.component}
                ))

    def receive(self, text_data=None, bytes_data=None, **kwargs):
        introduce(self.scope['user'])
        introduce_instance(self.component.zone.instance)
        json_data = json.loads(text_data)
        self.send_value = json_data.pop('send_value', False)
        for method, param in json_data.items():
            try:
                call = getattr(self.component.controller, method)
            except:
                continue
            try:
                if not param:
                    call()
                elif isinstance(param, list):
                    call(*param)
                elif isinstance(param, dict):
                    call(**param)
            except Exception as e:
                print("Exception:", str(e))
                continue


    def disconnect(self, console_log):
        if self._mqtt_client:
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except:
                pass
        print("STOPPING %s socket" % str(self.component))
