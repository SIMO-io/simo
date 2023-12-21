import json
import time
import logging
import threading
import sys
import json
import traceback
import pytz
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
import paho.mqtt.client as mqtt
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import paho.mqtt.publish as mqtt_publish

logger = logging.getLogger(__name__)


class BaseMqttAnnouncement:
    data = None
    TOPIC = None

    def publish(self):
        assert isinstance(self.TOPIC, str)
        assert self.data is not None
        mqtt_publish.single(
            self.TOPIC, json.dumps(self.data),
            hostname=settings.MQTT_HOST,
            port=settings.MQTT_PORT
        )


class ObjMqttAnnouncement(BaseMqttAnnouncement):

    def __init__(self, obj):
        self.data = {
            'obj_ct_pk': ContentType.objects.get_for_model(obj).pk,
            'obj_pk': obj.pk,
        }


class ObjectManagementEvent(ObjMqttAnnouncement):
    TOPIC = 'SIMO/management_event'

    def __init__(self, obj, event, dirty_fields=None, slave_id=None):
        super().__init__(obj)
        assert isinstance(event, str)
        assert event in ('added', 'removed', 'changed')
        self.data['event'] = event
        self.data['dirty_fields'] = dirty_fields if dirty_fields else {}
        for key, val in self.data['dirty_fields'].items():
            if type(val) not in (bool, int, float, str):
                self.data['dirty_fields'][key] = str(val)
        if slave_id:
            self.data['slave_id'] = slave_id



class Event(ObjMqttAnnouncement):
    TOPIC = 'SIMO/event'

    def __init__(self, obj, data=None):
        super().__init__(obj)
        self.data['data'] = data


class ObjectCommand(ObjMqttAnnouncement):
    TOPIC = 'SIMO/command'

    def __init__(self, obj, **kwargs):
        super().__init__(obj)
        self.data['kwargs'] = kwargs


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


def get_comp_set_val(msg, gateway=None):
    from .models import Component
    payload = json.loads(msg.payload)
    if 'set_val' not in payload.get("kwargs"):
        return (None, None)
    comp = get_event_obj(payload, model_class=Component, gateway=gateway)
    if not comp:
        return (None, None)
    set_val = payload["kwargs"]['set_val']
    return (comp, set_val)



class EventsStream:

    def __init__(self):
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        self.mqtt_client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)

    def run(self):
        last_tick = time.time()
        while True:
            if time.time() - last_tick > 1:
                self.on_tick()
                last_tick = time.time()
            self.mqtt_client.loop()

    def _on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        mqtt_client.subscribe(Event.TOPIC)

    def _on_mqtt_message(self, client, userdata, msg):
        if msg.topic != Event.TOPIC:
            return
        payload = json.loads(msg.payload)
        ct = ContentType.objects.get(pk=payload['obj_ct_pk'])
        obj = ct.get_object_for_this_type(pk=payload['obj_pk'])
        self.on_event(obj, payload['data'])

    def on_event(self, obj, event_data):
        """Override me to do something whenever an event occurs!"""
        pass

    def on_tick(self):
        """Override me to do something every second"""
        pass


class OnChangeMixin:

    on_change_fields = ('value', )

    def get_instance(self):
        # default for component
        return self.zone.instance.timezone

    def on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        mqtt_client.subscribe(ObjectManagementEvent.TOPIC)

    def on_mqtt_message(self, client, userdata, msg):
        payload = json.loads(msg.payload)
        if not self._on_change_function:
            return
        if payload['obj_pk'] != self.id:
            return
        if payload['obj_ct_pk'] != self._obj_ct_id:
            return
        if payload['event'] != 'changed':
            return
        if 'value' not in payload.get('dirty_fields', {}):
            return

        tz = pytz.timezone(self.gget_instance().timezone)
        timezone.activate(tz)

        self.refresh_from_db()

        try:
            self._on_change_function(self)
        except Exception:
            print(traceback.format_exc(), file=sys.stderr)

    def on_change(self, function):
        if function:
            self._mqtt_client = mqtt.Client()
            self._mqtt_client.on_connect = self.on_mqtt_connect
            self._mqtt_client.on_message = self.on_mqtt_message
            self._mqtt_client.connect(host=settings.MQTT_HOST,
                                     port=settings.MQTT_PORT)
            self._mqtt_client.loop_start()
            self._on_change_function = function
            self._obj_ct_id = ContentType.objects.get_for_model(self).pk
        elif self._mqtt_client:
            self._mqtt_client.disconnect()
            self._mqtt_client.loop_stop()
            self._mqtt_client = None
            self._on_change_function = None