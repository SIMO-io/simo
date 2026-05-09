import json
import sys
import time
import threading
import traceback
import paho.mqtt.client as mqtt
from django.core.management.base import BaseCommand
from django.conf import settings

from simo.users.models import User, InstanceUser, ComponentPermission
from simo.users.utils import user_context
from simo.core.models import Component
from simo.core.utils.mqtt import connect_with_retry, install_reconnect_handler
from simo.core.throttling import check_throttle, SimpleRequest


CONTROL_PREFIX = 'SIMO/user'


class Command(BaseCommand):
    help = 'Run MQTT control bridge to execute component controller methods from app MQTT requests.'

    def handle(self, *args, **options):
        stop_event = threading.Event()
        client = mqtt.Client()
        client.username_pw_set('root', settings.SECRET_KEY)
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        client.on_disconnect = self.on_disconnect
        # Back off on reconnects to avoid busy-spin during outages
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        # Route Paho logs to Python logging for visibility
        try:
            client.enable_logger()
        except Exception:
            pass

        install_reconnect_handler(
            client,
            stop_event=stop_event,
            description='App MQTT control'
        )
        if not connect_with_retry(
            client,
            stop_event=stop_event,
            description='App MQTT control'
        ):
            return

        client.loop_start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            try:
                client.loop_stop()
            except Exception:
                pass
            try:
                client.disconnect()
            except Exception:
                pass

    def on_connect(self, client, userdata, flags, rc):
        # SIMO/user/+/control/#
        client.subscribe(f'{CONTROL_PREFIX}/+/control/#', qos=1)

    def on_message(self, client, userdata, msg):
        user_id = None
        request_id = None
        try:
            print("Control: ", msg.topic)
            parts = msg.topic.split('/')
            # SIMO/user/<user-id>/control/<instance-uid>/Component/<component-id>
            if len(parts) < 7 or parts[0] != 'SIMO' or parts[1] != 'user' or parts[3] != 'control':
                return
            user_id = int(parts[2])
            instance_uid = parts[4]
            if parts[5] != 'Component':
                return
            try:
                component_id = int(parts[6])
            except Exception:
                payload, request_id = self.get_payload(msg)
                self.respond(client, user_id, request_id, ok=False, error='Invalid component id')
                return

            payload, request_id = self.get_payload(msg)
            if payload is None:
                return

            user = User.objects.filter(id=user_id).first()
            if not user or not user.is_active:
                self.respond(client, user_id, request_id, ok=False, error='Inactive or unknown user')
                return

            # Throttle MQTT control per authenticated user (per hub ban).
            wait = check_throttle(
                request=SimpleRequest(user=user),
                scope='mqtt.control',
            )
            if wait > 0:
                self.respond(client, user_id, request_id, ok=False, error='Rate limit exceeded')
                return

            component = Component.objects.filter(
                id=component_id, zone__instance__uid=instance_uid
            ).first()
            if not component:
                self.respond(client, user_id, request_id, ok=False, error='Component not found')
                return

            if not self.user_can_control_component(user, instance_uid, component):
                self.respond(client, user_id, request_id, ok=False, error='Permission denied')
                return

            with user_context(user):
                sub_id = payload.get('subcomponent_id')
                method = payload.get('method')
                args = payload.get('args', [])
                kwargs = payload.get('kwargs', {})
                if method in (None, 'id', 'secret') or str(method).startswith('_'):
                    self.respond(client, user_id, request_id, ok=False, error='Method not allowed')
                    return

                # Choose target component (main or subcomponent)
                target = component
                if sub_id:
                    try:
                        target = component.slaves.get(pk=sub_id)
                    except Exception:
                        self.respond(client, user_id, request_id, ok=False, error='Subcomponent not found')
                        return

                # Prepare controller and call
                target.prepare_controller()
                if not target.controller:
                    self.respond(client, user_id, request_id, ok=False, error='Component has no controller')
                    return
                if method not in set(target.get_controller_methods()):
                    self.respond(client, user_id, request_id, ok=False, error=f'Method {method} not allowed')
                    return
                if not hasattr(target, method):
                    self.respond(client, user_id, request_id, ok=False, error=f'Method {method} not found')
                    return
                call = getattr(target, method)
                try:
                    if isinstance(args, list) and isinstance(kwargs, dict):
                        result = call(*args, **kwargs)
                    elif isinstance(args, list):
                        result = call(*args)
                    elif isinstance(kwargs, dict):
                        result = call(**kwargs)
                    else:
                        result = call()
                    self.respond(client, user_id, request_id, ok=True, result=result)
                except Exception:
                    self.respond(client, user_id, request_id, ok=False, error=''.join(traceback.format_exception(*sys.exc_info())))
        except Exception:
            # Never crash the consumer
            self.respond(
                client,
                user_id,
                request_id,
                ok=False,
                error=''.join(traceback.format_exception(*sys.exc_info())),
            )

    def on_disconnect(self, client, userdata, rc):
        # Non-zero rc means unexpected disconnect. Paho will back off and retry.
        if rc != 0:
            try:
                print(f"Control MQTT disconnect rc={rc}; reconnecting with backoff...", file=sys.stderr)
            except Exception:
                pass

    def respond(self, client, user_id, request_id, ok=True, result=None, error=None):
        if not user_id or not request_id:
            return
        topic = f'{CONTROL_PREFIX}/{user_id}/control-resp/{request_id}'
        payload = {'ok': ok}
        if ok:
            payload['result'] = result
        else:
            payload['error'] = error
        client.publish(topic, json.dumps(payload), qos=1, retain=False)

    def get_payload(self, msg):
        try:
            payload = json.loads(msg.payload or '{}')
        except Exception:
            return None, None
        if not isinstance(payload, dict):
            return None, None
        return payload, payload.get('request_id')

    def user_can_control_component(self, user, instance_uid, component):
        if user.is_master:
            return True

        instance_user = InstanceUser.objects.select_related('role').filter(
            user=user,
            instance__uid=instance_uid,
            is_active=True,
        ).first()
        if not instance_user:
            return False

        role = instance_user.role
        if role.is_superuser or role.is_owner:
            return True

        return ComponentPermission.objects.filter(
            role=role,
            component=component,
            write=True,
        ).exists()
