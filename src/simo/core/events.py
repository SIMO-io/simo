import logging
import sys
import json
import traceback
import pytz
import inspect
import threading
import atexit
import weakref
import os
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
import paho.mqtt.client as mqtt
from django.utils import timezone
from .mqtt_hub import get_mqtt_hub
from simo.core.utils.mqtt import connect_with_retry, install_reconnect_handler
from .utils.model_helpers import dirty_fields_to_current_values


_watcher_context = threading.local()


def set_current_watcher_stop_event(event):
    _watcher_context.stop_event = event


def clear_current_watcher_stop_event():
    if hasattr(_watcher_context, 'stop_event'):
        del _watcher_context.stop_event


def get_current_watcher_stop_event():
    return getattr(_watcher_context, 'stop_event', None)

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
        hub.publish(self.get_topic(), json.dumps(self.data, default=str), retain=retain)

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


class OnChangeMixin:

    _on_change_function = None
    on_change_fields = ('value', )
    _mqtt_client = None
    _mqtt_sub_tokens = None
    _mqtt_stop_event = None
    _mqtt_cleanup_registered = False
    _watcher_owner_event = None
    _on_change_since = None

    def _register_mqtt_cleanup(self):
        if self._mqtt_cleanup_registered:
            return
        self._mqtt_cleanup_registered = True
        self_ref = weakref.ref(self)

        def _cleanup():
            obj = self_ref()
            if not obj:
                return
            client = getattr(obj, '_mqtt_client', None)
            stop_event = getattr(obj, '_mqtt_stop_event', None)
            if stop_event:
                stop_event.set()
            if client:
                try:
                    client.loop_stop()
                except Exception:
                    pass
                try:
                    client.disconnect()
                except Exception:
                    pass

        atexit.register(_cleanup)

    @staticmethod
    def _use_hub_watchers() -> bool:
        if get_current_watcher_stop_event():
            return False
        env = os.environ.get('SIMO_MQTT_WATCHERS_VIA_HUB')
        if env is not None:
            return env.strip().lower() in ('1', 'true', 'yes', 'on')
        # Enable by default while debugging (dev only)
        return bool(getattr(settings, 'MQTT_WATCHERS_VIA_HUB', True))

    def get_instance(self):
        # default for component
        return self.zone.instance

    def on_mqtt_connect(self, mqtt_client, userdata, flags, rc):
        event = ObjectChangeEvent(self.get_instance(), self)
        mqtt_client.subscribe(event.get_topic())

    def on_mqtt_message(self, client, userdata, msg):
        from simo.users.models import InstanceUser

        try:
            payload = json.loads(msg.payload)
        except Exception as e:
            return
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

        payload_ts = payload.get('timestamp', 0)
        since = getattr(self, '_on_change_since', None)
        if since and payload_ts <= since:
            return

        ts_now = timezone.now().timestamp()
        if payload_ts < ts_now - 10:
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
        use_hub = self._use_hub_watchers()
        if function:
            self._on_change_since = timezone.now().timestamp()
            # Clear previous bindings (both modes) to avoid duplicates
            if getattr(self, '_mqtt_sub_tokens', None):
                try:
                    hub = get_mqtt_hub()
                    for tok in self._mqtt_sub_tokens:
                        hub.unsubscribe(tok)
                except Exception:
                    pass
                self._mqtt_sub_tokens = None
            if getattr(self, '_mqtt_client', None):
                try:
                    self._mqtt_client.loop_stop()
                    self._mqtt_client.disconnect()
                except Exception:
                    pass
                self._mqtt_client = None

            # Set handler context before any message may arrive
            self._on_change_function = function
            self._obj_ct_id = ContentType.objects.get_for_model(self).pk

            if use_hub:
                # Subscribe via shared hub (single client per process)
                hub = get_mqtt_hub()
                topic = ObjectChangeEvent(self.get_instance(), self).get_topic()
                t1 = hub.subscribe(topic, self.on_mqtt_message)
                self._mqtt_sub_tokens = [t1]
            else:
                # Dedicated client per watcher
                self._mqtt_client = mqtt.Client()
                self._mqtt_client.username_pw_set('root', settings.SECRET_KEY)
                self._mqtt_client.on_message = self.on_mqtt_message

                def _on_connect(cli, userdata, flags, rc):
                    cli.subscribe(ObjectChangeEvent(self.get_instance(), self).get_topic())

                self._mqtt_client.on_connect = _on_connect
                try:
                    self._mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)
                except Exception:
                    pass
                self._mqtt_stop_event = threading.Event()
                parent_stop = get_current_watcher_stop_event()
                if parent_stop:
                    threading.Thread(
                        target=self._bridge_stop_events,
                        args=(parent_stop, self._mqtt_stop_event),
                        daemon=True
                    ).start()
                install_reconnect_handler(
                    self._mqtt_client,
                    stop_event=self._mqtt_stop_event,
                    description=f"OnChange watcher {self}",
                )
                try:
                    if not connect_with_retry(
                        self._mqtt_client,
                        stop_event=self._mqtt_stop_event,
                        description=f"OnChange watcher {self}",
                    ):
                        return
                except Exception:
                    raise
                self._mqtt_client.loop_start()
                self._register_mqtt_cleanup()

            owner_event = get_current_watcher_stop_event()
            self._watcher_owner_event = owner_event
            _register_component_watcher(self, owner_event)
        else:
            # Unbind watcher
            self._on_change_since = None
            if getattr(self, '_mqtt_sub_tokens', None):
                try:
                    hub = get_mqtt_hub()
                    for tok in self._mqtt_sub_tokens:
                        hub.unsubscribe(tok)
                except Exception:
                    pass
                self._mqtt_sub_tokens = None
            if getattr(self, '_mqtt_client', None):
                try:
                    if self._mqtt_stop_event:
                        self._mqtt_stop_event.set()
                    self._mqtt_client.loop_stop()
                    self._mqtt_client.disconnect()
                except Exception:
                    pass
                self._mqtt_client = None
                self._mqtt_stop_event = None
                self._mqtt_cleanup_registered = False
            _unregister_component_watcher(self)
            self._on_change_function = None

    @staticmethod
    def _bridge_stop_events(parent_event, child_event):
        try:
            parent_event.wait()
        except Exception:
            return
        child_event.set()
_watcher_context = threading.local()
_watcher_registry_lock = threading.Lock()
_watcher_registry = {}


def set_current_watcher_stop_event(event):
    _watcher_context.stop_event = event


def clear_current_watcher_stop_event():
    if hasattr(_watcher_context, 'stop_event'):
        del _watcher_context.stop_event


def get_current_watcher_stop_event():
    return getattr(_watcher_context, 'stop_event', None)


def _register_component_watcher(component, owner_event):
    if owner_event is None:
        return
    with _watcher_registry_lock:
        watchers = _watcher_registry.setdefault(owner_event, weakref.WeakSet())
        watchers.add(component)
    component._watcher_owner_event = owner_event


def _unregister_component_watcher(component):
    owner_event = getattr(component, '_watcher_owner_event', None)
    if not owner_event:
        return
    with _watcher_registry_lock:
        watchers = _watcher_registry.get(owner_event)
        if watchers and component in watchers:
            watchers.discard(component)
            if not watchers:
                _watcher_registry.pop(owner_event, None)
    component._watcher_owner_event = None


def cleanup_watchers_for_event(owner_event):
    if owner_event is None:
        return
    with _watcher_registry_lock:
        watchers = _watcher_registry.pop(owner_event, None)
    if not watchers:
        return
    for component in list(watchers):
        try:
            component.on_change(None)
        except Exception:
            logger.exception("Failed to cleanup watcher for %s", component)
