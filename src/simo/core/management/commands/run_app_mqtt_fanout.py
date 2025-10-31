import json
import sys
import traceback
import paho.mqtt.client as mqtt
from django.core.management.base import BaseCommand
from django.conf import settings
from simo.core.events import get_event_obj
from simo.core.models import Component, Zone, Category
from simo.users.models import User, InstanceUser, ComponentPermission


OBJ_STATE_PREFIX = 'SIMO/obj-state'
FEED_PREFIX = 'SIMO/user'


class Command(BaseCommand):
    help = 'Authorizing fanout for app feeds: replicate internal obj-state to per-user feed topics.'

    def handle(self, *args, **options):
        self.client = mqtt.Client()
        self.client.username_pw_set('root', settings.SECRET_KEY)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        # Back off on reconnects to avoid busy-spin during outages
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        # Route Paho logs to Python logging for visibility
        try:
            self.client.enable_logger()
        except Exception:
            pass
        self.client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
        try:
            # Blocking network loop with built-in reconnect/backoff
            self.client.loop_forever(retry_first_connection=True)
        finally:
            try:
                self.client.disconnect()
            except Exception:
                pass

    def on_connect(self, client, userdata, flags, rc):
        client.subscribe(f'{OBJ_STATE_PREFIX}/#')

    def on_message(self, client, userdata, msg):
        try:
            print("Fanout: ", msg.topic)
            topic_parts = msg.topic.split('/')
            # SIMO/obj-state/<instance-uid>/<Model>/<id>
            if len(topic_parts) < 5 or topic_parts[0] != 'SIMO' or topic_parts[1] != 'obj-state':
                return
            instance_uid = topic_parts[2]
            model_name = topic_parts[3]
            obj_id = topic_parts[4]

            # Only forward instance-scoped objects that the app cares about
            payload = json.loads(msg.payload or '{}')

            # Resolve object if needed (mainly for Components to do permission checks)
            target_obj = None
            if model_name == 'Component':
                target_obj = get_event_obj(payload, model_class=Component)
                if not target_obj:
                    return
            elif model_name == 'Zone':
                target_obj = get_event_obj(payload, model_class=Zone)
            elif model_name == 'Category':
                target_obj = get_event_obj(payload, model_class=Category)
            elif model_name == 'InstanceUser':
                # presence updates; no need to resolve explicitly
                pass
            else:
                # Ignore other objects for feed
                return

            publish_to_users = set([
                m.id for m in User.objects.filter(is_master=True) if m.is_active
            ])
            for iu in InstanceUser.objects.filter(
                instance__uid=instance_uid, is_active=True
            ).select_related('user', 'role'):
                if iu.user.is_master:
                    publish_to_users.add(iu.user.id)
                    continue
                if iu.role.is_superuser:
                    publish_to_users.add(iu.user.id)
                    continue
                if model_name != 'Component':
                    publish_to_users.add(iu.user.id)
                    continue
                if ComponentPermission.objects.filter(
                    role=iu.role,
                    component_id=target_obj.id,
                    component__zone__instance__uid=instance_uid,
                    read=True,
                ).exists():
                    publish_to_users.add(iu.user.id)
                    continue

            for user_id in publish_to_users:
                feed_topic = f'{FEED_PREFIX}/{user_id}/feed/{instance_uid}/{model_name}/{obj_id}'
                client.publish(feed_topic, msg.payload, qos=0, retain=True)
        except Exception:
            # Never crash the consumer
            print('Fanout error:', ''.join(traceback.format_exception(*sys.exc_info())), file=sys.stderr)

    def on_disconnect(self, client, userdata, rc):
        # Non-zero rc means unexpected disconnect. Paho will back off and retry.
        if rc != 0:
            try:
                print(f"Fanout MQTT disconnect rc={rc}; reconnecting with backoff...", file=sys.stderr)
            except Exception:
                pass
