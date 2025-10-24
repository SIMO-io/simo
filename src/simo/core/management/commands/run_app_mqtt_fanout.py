import json
import sys
import traceback
import paho.mqtt.client as mqtt
from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.contenttypes.models import ContentType

from simo.core.events import get_event_obj
from simo.core.models import Component, Zone, Category
from simo.core.api import get_main_components_ids
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
        self.client.connect(host=settings.MQTT_HOST, port=settings.MQTT_PORT)
        try:
            while True:
                self.client.loop()
        finally:
            try:
                self.client.disconnect()
            except Exception:
                pass

    def on_connect(self, client, userdata, flags, rc):
        client.subscribe(f'{OBJ_STATE_PREFIX}/#')

    def on_message(self, client, userdata, msg):
        try:
            topic_parts = msg.topic.split('/')
            # SIMO/obj-state/<instance-id>/<Model>-<id>
            if len(topic_parts) < 4 or topic_parts[0] != 'SIMO' or topic_parts[1] != 'obj-state':
                return
            instance_id_str = topic_parts[2]
            obj_part = topic_parts[3]
            try:
                instance_id = int(instance_id_str) if instance_id_str != 'global' else None
            except Exception:
                return

            # Only forward instance-scoped objects that the app cares about
            payload = json.loads(msg.payload or '{}')
            model_name, obj_id = (obj_part.split('-', 1) + [None])[:2]

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

            # Fanout to users active on this instance
            if instance_id is None:
                return
            active_roles = InstanceUser.objects.filter(instance_id=instance_id, is_active=True).select_related('user')

            # Cache main components list for this instance
            main_ids = set(get_main_components_ids(target_obj.zone.instance) if target_obj and isinstance(target_obj, Component) else [])

            for iu in active_roles:
                user = iu.user
                # Decide forwarding per user
                allowed = True
                if model_name == 'Component' and target_obj:
                    if user.is_master:
                        allowed = True
                    else:
                        if target_obj.id in main_ids:
                            allowed = True
                        else:
                            allowed = ComponentPermission.objects.filter(
                                role__in=user.roles.all(),
                                component_id=target_obj.id,
                                component__zone__instance_id=instance_id,
                                read=True,
                            ).exists()
                # InstanceUser/Zone/Category always forwarded to members of the instance
                if not allowed:
                    continue

                feed_topic = f'{FEED_PREFIX}/{user.id}/feed/{instance_id}/{model_name}-{obj_id}'
                client.publish(feed_topic, msg.payload, qos=0, retain=True)
        except Exception:
            # Never crash the consumer
            print('Fanout error:', ''.join(traceback.format_exception(*sys.exc_info())), file=sys.stderr)

