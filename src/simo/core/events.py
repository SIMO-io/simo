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
from .mqtt_hub import get_mqtt_hub

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
        self.data['timestamp'] = timezone.now().timestamp()
        # Use shared hub client instead of opening a new socket per publish
        hub = get_mqtt_hub()
        hub.publish(
            self.get_topic(), json.dumps(self.data, default=str), retain=retain
        )

    def get_topic(self):
        return self.TOPIC


class ObjectChangeEvent(ObjMqttAnnouncement):
    TOPIC = 'SIMO/obj-state'

    def __init__(self, instance, obj, **kwargs):
        self.instance = instance
        self.obj = obj
        super().__init__(obj)
        self.data.update(**kwargs)

    def get_topic(self):
        return f"{self.TOPIC}/{self.instance.uid if self.instance else 'global'}/" \
               f"{type(self.obj).__name__}/{self.data['obj_pk']}"

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


def dirty_fields_to_current_values(instance, dirty_fields):
    """Return a mapping of changed field names to the instance's current values.

    - Avoids extra DB hits by reading values from the in-memory instance.
    - For ForeignKey fields, emits the underlying ``<field>_id`` when available
      to keep the payload JSON-serializable and consistent.
    """
    if not dirty_fields:
        return {}

    current = {}
    for field_name in dirty_fields.keys():
        try:
            model_field = instance._meta.get_field(field_name)
            # Many-to-many changes are not handled here (not part of default dirty_fields)
            if getattr(model_field, 'many_to_many', False):
                continue
            if getattr(model_field, 'is_relation', False) and hasattr(instance, f"{field_name}_id"):
                current[field_name] = getattr(instance, f"{field_name}_id")
            else:
                current[field_name] = getattr(instance, field_name, None)
        except Exception:
            # Field might not be a real model field (unlikely); fallback to attribute
            current[field_name] = getattr(instance, field_name, None)
    return current


class OnChangeMixin:

    _on_change_function = None
    on_change_fields = ('value', )
    _mqtt_client = None  # kept for backward compatibility; not used with hub
    _mqtt_sub_token = None

    def get_instance(self):
        # default for component
        return self.zone.instance

    def on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        event = ObjectChangeEvent(self.get_instance(), self)
        mqtt_client.subscribe(event.get_topic())

    def on_mqtt_message(self, client, userdata, msg):
        from simo.users.models import InstanceUser

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
                break

        if not has_changed:
            return

        if payload.get('timestamp', 0) < timezone.now().timestamp() - 10:
            return

        tz = pytz.timezone(self.get_instance().timezone)
        timezone.activate(tz)

        self.refresh_from_db()

        no_args = len(inspect.getfullargspec(self._on_change_function).args)
        if inspect.ismethod(self._on_change_function):
            no_args -= 1
        args = []
        if no_args > 0:
            args = [self]
        if no_args > 1:
            actor = payload.get('actor')
            if isinstance(actor, InstanceUser):
                args.append(actor)
        try:
            self._on_change_function(*args)
        except Exception:
            print(traceback.format_exc(), file=sys.stderr)

    def on_change(self, function):
        hub = get_mqtt_hub()
        if function:
            # If already subscribed, refresh the subscription
            if getattr(self, '_mqtt_sub_token', None):
                try:
                    hub.unsubscribe(self._mqtt_sub_token)
                except Exception:
                    pass
                self._mqtt_sub_token = None
            # Subscribe via hub and store subscription token for cleanup
            event = ObjectChangeEvent(self.get_instance(), self)
            topic = event.get_topic()
            # Ensure our callback is bound with expected signature
            token = hub.subscribe(topic, self.on_mqtt_message)
            self._mqtt_sub_token = token
            self._on_change_function = function
            self._obj_ct_id = ContentType.objects.get_for_model(self).pk
        else:
            # Unsubscribe if previously subscribed
            if getattr(self, '_mqtt_sub_token', None):
                try:
                    hub.unsubscribe(self._mqtt_sub_token)
                except Exception:
                    pass
                self._mqtt_sub_token = None
            self._on_change_function = None
