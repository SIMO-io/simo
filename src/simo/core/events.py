import logging
import sys
import json
import traceback
import pytz
import inspect
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
import paho.mqtt.client as mqtt
from django.utils import timezone
import paho.mqtt.publish as mqtt_publish

logger = logging.getLogger(__name__)


class ObjMqttAnnouncement:
    data = None
    TOPIC = None

    def __init__(self, obj=None):
        if obj:
            self.data = {
                'obj_ct_pk': ContentType.objects.get_for_model(obj).pk,
                'obj_pk': obj.pk,
            }
        else:
            self.data = {}

    def publish(self, retain=False):
        assert isinstance(self.TOPIC, str)
        assert self.data is not None
        mqtt_publish.single(
            self.get_topic(), json.dumps(self.data, default=str),
            retain=retain,
            hostname=settings.MQTT_HOST,
            port=settings.MQTT_PORT,
            auth={'username': 'root', 'password': settings.SECRET_KEY},
        )

    def get_topic(self):
        return self.TOPIC


class ObjectChangeEvent(ObjMqttAnnouncement):
    TOPIC = 'SIMO/obj-state'

    def __init__(self, instance, obj, **kwargs):
        self.instance = instance
        self.obj = obj
        super().__init__(obj)
        for key, val in kwargs.items():
            self.data[key] = val

    def get_topic(self):
        return f"{self.TOPIC}/{self.instance.id if self.instance else 'global'}/" \
               f"{type(self.obj).__name__}-{self.data['obj_pk']}"

    def publish(self, retain=True):
        return super().publish(retain=retain)


class GatewayObjectCommand(ObjMqttAnnouncement):
    "Used internally to send commands to corresponding gateway handlers"

    TOPIC = 'SIMO/gw-command'

    def __init__(self, gateway, obj=None, command=None, **kwargs):
        self.gateway = gateway
        super().__init__(obj)
        self.data['command'] = command
        for key, val in kwargs.items():
            self.data[key] = val

    def get_topic(self):
        return f'{self.TOPIC}/{self.gateway.id}'


def get_event_obj(payload, model_class=None, gateway=None):
    try:
        ct = ContentType.objects.get(pk=payload['obj_ct_pk'])
    except:
        return

    if model_class and model_class != ct.model_class():
        return

    obj = ct.get_object_for_this_type(pk=payload['obj_pk'])
    if gateway and getattr(obj, 'gateway', None) != gateway:
        return

    return obj


class OnChangeMixin:

    _on_change_function = None
    on_change_fields = ('value', )
    _mqtt_client = None

    def get_instance(self):
        # default for component
        return self.zone.instance

    def on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        event = ObjectChangeEvent(self.get_instance(), self)
        mqtt_client.subscribe(event.get_topic())

    def on_mqtt_message(self, client, userdata, msg):
        payload = json.loads(msg.payload)
        if not self._on_change_function:
            return
        if payload['obj_pk'] != self.id:
            return
        if payload['obj_ct_pk'] != self._obj_ct_id:
            return

        has_changed = False
        for key, val in payload.get('dirty_fields', {}).items():
            if key in self.on_change_fields:
                has_changed = True

        if not has_changed:
            return

        if payload.get('timestamp', 0) < timezone.now().timestamp() - 10:
            return

        tz = pytz.timezone(self.get_instance().timezone)
        timezone.activate(tz)

        self.refresh_from_db()

        if inspect.getfullargspec(self._on_change_function).args:
            try:
                self._on_change_function(self)
            except Exception:
                print(traceback.format_exc(), file=sys.stderr)
        else:
            try:
                self._on_change_function()
            except Exception:
                print(traceback.format_exc(), file=sys.stderr)

    def on_change(self, function):
        if function:
            self._mqtt_client = mqtt.Client()
            self._mqtt_client.username_pw_set('root', settings.SECRET_KEY)
            self._mqtt_client.on_connect = self.on_mqtt_connect
            self._mqtt_client.on_message = self.on_mqtt_message
            self._mqtt_client.connect(
                host=settings.MQTT_HOST, port=settings.MQTT_PORT
            )
            self._mqtt_client.loop_start()
            self._on_change_function = function
            self._obj_ct_id = ContentType.objects.get_for_model(self).pk
        elif self._mqtt_client:
            self._mqtt_client.disconnect()
            self._mqtt_client.loop_stop()
            self._mqtt_client = None
            self._on_change_function = None