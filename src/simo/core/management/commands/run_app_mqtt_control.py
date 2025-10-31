import json
import sys
import traceback
import paho.mqtt.client as mqtt
from django.core.management.base import BaseCommand
from django.conf import settings

from simo.users.models import User, InstanceUser, ComponentPermission
from simo.users.utils import introduce_user
from simo.core.models import Component


CONTROL_PREFIX = 'SIMO/user'


class Command(BaseCommand):
    help = 'Run MQTT control bridge to execute component controller methods from app MQTT requests.'

    def handle(self, *args, **options):
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
        client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
        try:
            # Blocking network loop with built-in reconnect/backoff
            client.loop_forever(retry_first_connection=True)
        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    def on_connect(self, client, userdata, flags, rc):
        # SIMO/user/+/control/#
        client.subscribe(f'{CONTROL_PREFIX}/+/control/#')

    def on_message(self, client, userdata, msg):
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
                return

            # Resolve user and permission
            user = User.objects.filter(id=user_id).first()
            if not user or not user.is_active:
                return
            if not user.is_master:
                # Must be active on instance
                if not InstanceUser.objects.filter(
                    user=user, instance__uid=instance_uid, is_active=True
                ).exists():
                    return
                # Must have write permission on the component
                has_write = ComponentPermission.objects.filter(
                    role__in=user.roles.all(),
                    component_id=component_id,
                    component__zone__instance__uid=instance_uid,
                    write=True,
                ).exists()
                if not has_write:
                    return

            # Execute controller method
            component = Component.objects.filter(
                id=component_id, zone__instance__uid=instance_uid
            ).first()
            if not component:
                return

            introduce_user(user)
            payload = json.loads(msg.payload or '{}')
            request_id = payload.get('request_id')
            sub_id = payload.get('subcomponent_id')
            method = payload.get('method')
            args = payload.get('args', [])
            kwargs = payload.get('kwargs', {})
            if method in (None, 'id', 'secret') or str(method).startswith('_'):
                return

            # Choose target component (main or subcomponent)
            target = component
            if sub_id:
                try:
                    target = component.slaves.get(pk=sub_id)
                except Exception:
                    return

            # Prepare controller and call
            target.prepare_controller()
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
            pass

    def on_disconnect(self, client, userdata, rc):
        # Non-zero rc means unexpected disconnect. Paho will back off and retry.
        if rc != 0:
            try:
                print(f"Control MQTT disconnect rc={rc}; reconnecting with backoff...", file=sys.stderr)
            except Exception:
                pass

    def respond(self, client, user_id, request_id, ok=True, result=None, error=None):
        if not request_id:
            return
        topic = f'{CONTROL_PREFIX}/{user_id}/control-resp/{request_id}'
        payload = {'ok': ok}
        if ok:
            payload['result'] = result
        else:
            payload['error'] = error
        client.publish(topic, json.dumps(payload), qos=0, retain=False)
