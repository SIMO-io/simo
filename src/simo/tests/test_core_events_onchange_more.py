import json
import os
import threading
from types import SimpleNamespace
from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from simo.core.models import Component, Gateway, Zone

from .base import (
    BaseSimoTestCase,
    mk_instance,
    mk_instance_user,
    mk_role,
    mk_user,
)


class FakeMqttClient:
    def __init__(self):
        self.on_connect = None
        self.on_message = None
        self.loop_started = 0
        self.loop_stopped = 0
        self.disconnected = 0
        self.subscribed = []

    def username_pw_set(self, *_args, **_kwargs):
        return None

    def reconnect_delay_set(self, **_kwargs):
        return None

    def loop_start(self):
        self.loop_started += 1

    def loop_stop(self):
        self.loop_stopped += 1

    def disconnect(self):
        self.disconnected += 1

    def subscribe(self, topic):
        self.subscribed.append(topic)


class EventsOnChangeMoreTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        self.comp = Component.objects.create(
            name='C',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )
        self.ct_id = ContentType.objects.get_for_model(Component).pk

    def test_use_hub_watchers_env_false_disables_hub(self):
        from simo.core.events import clear_current_watcher_stop_event

        clear_current_watcher_stop_event()
        with mock.patch.dict(os.environ, {'SIMO_MQTT_WATCHERS_VIA_HUB': '0'}):
            self.assertFalse(self.comp._use_hub_watchers())

    def test_on_change_dedicated_client_binds_and_subscribes(self):
        with (
            mock.patch.dict(os.environ, {'SIMO_MQTT_WATCHERS_VIA_HUB': '0'}),
            mock.patch('simo.core.events.mqtt.Client', autospec=True, side_effect=FakeMqttClient),
            mock.patch('simo.core.events.install_reconnect_handler', autospec=True),
            mock.patch('simo.core.events.connect_with_retry', autospec=True, return_value=True),
        ):
            self.comp.on_change(lambda _c: None)

        self.assertIsNotNone(self.comp._mqtt_client)
        self.assertEqual(self.comp._mqtt_client.loop_started, 1)

        self.comp._mqtt_client.on_connect(self.comp._mqtt_client, None, None, 0)
        self.assertEqual(len(self.comp._mqtt_client.subscribed), 1)

    def test_on_change_unbinds_stops_client_and_clears_handler(self):
        with (
            mock.patch.dict(os.environ, {'SIMO_MQTT_WATCHERS_VIA_HUB': '0'}),
            mock.patch('simo.core.events.mqtt.Client', autospec=True, side_effect=FakeMqttClient),
            mock.patch('simo.core.events.install_reconnect_handler', autospec=True),
            mock.patch('simo.core.events.connect_with_retry', autospec=True, return_value=True),
        ):
            self.comp.on_change(lambda _c: None)
            cli = self.comp._mqtt_client
            stop_event = self.comp._mqtt_stop_event
            self.comp.on_change(None)

        self.assertTrue(stop_event.is_set())
        self.assertEqual(cli.loop_stopped, 1)
        self.assertEqual(cli.disconnected, 1)
        self.assertIsNone(self.comp._on_change_function)

    def test_on_mqtt_message_ignored_without_handler(self):
        msg = SimpleNamespace(
            payload=json.dumps(
                {
                    'obj_pk': self.comp.id,
                    'obj_ct_pk': self.ct_id,
                    'dirty_fields': {'value': True},
                    'timestamp': timezone.now().timestamp(),
                }
            ).encode()
        )

        with mock.patch.object(self.comp, 'refresh_from_db', autospec=True) as refresh:
            self.comp._on_change_function = None
            self.comp.on_mqtt_message(None, None, msg)
        refresh.assert_not_called()

    def test_on_mqtt_message_ignored_when_content_type_mismatches(self):
        called = []

        def handler(obj):
            called.append(obj.id)

        self.comp._on_change_function = handler
        self.comp._obj_ct_id = self.ct_id
        self.comp._on_change_since = timezone.now().timestamp() - 1

        msg = SimpleNamespace(
            payload=json.dumps(
                {
                    'obj_pk': self.comp.id,
                    'obj_ct_pk': self.ct_id + 999,
                    'dirty_fields': {'value': True},
                    'timestamp': timezone.now().timestamp(),
                }
            ).encode()
        )
        self.comp.on_mqtt_message(None, None, msg)
        self.assertEqual(called, [])

    def test_on_mqtt_message_ignored_when_timestamp_before_since(self):
        called = []

        def handler(obj):
            called.append(obj.id)

        self.comp._on_change_function = handler
        self.comp._obj_ct_id = self.ct_id
        since = timezone.now().timestamp()
        self.comp._on_change_since = since

        msg = SimpleNamespace(
            payload=json.dumps(
                {
                    'obj_pk': self.comp.id,
                    'obj_ct_pk': self.ct_id,
                    'dirty_fields': {'value': True},
                    'timestamp': since - 0.1,
                }
            ).encode()
        )
        self.comp.on_mqtt_message(None, None, msg)
        self.assertEqual(called, [])

    def test_on_change_hub_mode_unsubscribes_previous_tokens(self):
        hub = mock.Mock()
        hub.subscribe.side_effect = [('t', 0), ('t', 1)]

        with (
            mock.patch.dict(os.environ, {'SIMO_MQTT_WATCHERS_VIA_HUB': '1'}),
            mock.patch('simo.core.events.get_mqtt_hub', autospec=True, return_value=hub),
        ):
            self.comp.on_change(lambda _c: None)
            self.comp.on_change(lambda _c: None)

        hub.unsubscribe.assert_called_once_with(('t', 0))

    def test_cleanup_watchers_for_event_unbinds_registered_components(self):
        from simo.core.events import (
            cleanup_watchers_for_event,
            set_current_watcher_stop_event,
            clear_current_watcher_stop_event,
        )

        owner_event = threading.Event()

        with (
            mock.patch.dict(os.environ, {'SIMO_MQTT_WATCHERS_VIA_HUB': '1'}),
            mock.patch('simo.core.events.mqtt.Client', autospec=True, side_effect=FakeMqttClient),
            mock.patch('simo.core.events.install_reconnect_handler', autospec=True),
            mock.patch('simo.core.events.connect_with_retry', autospec=True, return_value=True),
        ):
            set_current_watcher_stop_event(owner_event)
            try:
                self.comp.on_change(lambda _c: None)
            finally:
                clear_current_watcher_stop_event()

            self.assertIsNotNone(self.comp._mqtt_client)
            cleanup_watchers_for_event(owner_event)

        self.assertIsNone(self.comp._on_change_function)
        self.assertIsNone(getattr(self.comp, '_watcher_owner_event', None))
        self.assertIsNone(self.comp._mqtt_client)

    def test_on_mqtt_message_calls_zero_arg_handler(self):
        called = []

        def handler():
            called.append(True)

        self.comp._on_change_function = handler
        self.comp._obj_ct_id = self.ct_id
        self.comp._on_change_since = timezone.now().timestamp() - 1

        msg = SimpleNamespace(
            payload=json.dumps(
                {
                    'obj_pk': self.comp.id,
                    'obj_ct_pk': self.ct_id,
                    'dirty_fields': {'value': True},
                    'timestamp': timezone.now().timestamp(),
                }
            ).encode()
        )
        self.comp.on_mqtt_message(None, None, msg)
        self.assertEqual(called, [True])

    def test_on_mqtt_message_calls_one_arg_handler(self):
        called = []

        def handler(obj):
            called.append(obj.id)

        self.comp._on_change_function = handler
        self.comp._obj_ct_id = self.ct_id
        self.comp._on_change_since = timezone.now().timestamp() - 1

        msg = SimpleNamespace(
            payload=json.dumps(
                {
                    'obj_pk': self.comp.id,
                    'obj_ct_pk': self.ct_id,
                    'dirty_fields': {'value': True},
                    'timestamp': timezone.now().timestamp(),
                }
            ).encode()
        )
        self.comp.on_mqtt_message(None, None, msg)
        self.assertEqual(called, [self.comp.id])

    def test_on_mqtt_message_calls_two_arg_handler_with_instance_user_actor(self):
        inst = self.inst
        user = mk_user('owner@example.com', 'Owner')
        role = mk_role(inst, is_owner=True)
        actor_iuser = mk_instance_user(user, inst, role)

        called = []

        def handler(obj, actor):
            called.append(
                (
                    obj.id,
                    actor.id if actor else None,
                    actor.role.is_owner if actor else None,
                )
            )

        self.comp._on_change_function = handler
        self.comp._obj_ct_id = self.ct_id
        self.comp._on_change_since = timezone.now().timestamp() - 1

        msg = SimpleNamespace(
            payload=json.dumps(
                {
                    'obj_pk': self.comp.id,
                    'obj_ct_pk': self.ct_id,
                    'dirty_fields': {'value': True},
                    'timestamp': timezone.now().timestamp(),
                    # Historically the payload carried `actor`, but it becomes a string.
                    'actor': str(actor_iuser),
                    'actor_instance_user_id': actor_iuser.id,
                }
            ).encode()
        )
        self.comp.on_mqtt_message(None, None, msg)
        self.assertEqual(called, [(self.comp.id, actor_iuser.id, True)])

    def test_on_mqtt_message_actor_user_id_fallback_resolves_instance_user(self):
        inst = self.inst
        user = mk_user('user@example.com', 'User')
        role = mk_role(inst, is_owner=False)
        actor_iuser = mk_instance_user(user, inst, role)

        called = []

        def handler(_obj, actor):
            called.append(actor.id if actor else None)

        self.comp._on_change_function = handler
        self.comp._obj_ct_id = self.ct_id
        self.comp._on_change_since = timezone.now().timestamp() - 1

        msg = SimpleNamespace(
            payload=json.dumps(
                {
                    'obj_pk': self.comp.id,
                    'obj_ct_pk': self.ct_id,
                    'dirty_fields': {'value': True},
                    'timestamp': timezone.now().timestamp(),
                    'actor_user_id': user.id,
                }
            ).encode()
        )
        self.comp.on_mqtt_message(None, None, msg)
        self.assertEqual(called, [actor_iuser.id])

    def test_on_mqtt_message_calls_two_arg_handler_with_none_actor_when_missing(self):
        class Handler:
            def __init__(self):
                self.called = []

            def cb(self, obj, actor):
                self.called.append((obj.id, actor))

        h = Handler()
        self.comp._on_change_function = h.cb
        self.comp._obj_ct_id = self.ct_id
        self.comp._on_change_since = timezone.now().timestamp() - 1

        msg = SimpleNamespace(
            payload=json.dumps(
                {
                    'obj_pk': self.comp.id,
                    'obj_ct_pk': self.ct_id,
                    'dirty_fields': {'value': True},
                    'timestamp': timezone.now().timestamp(),
                }
            ).encode()
        )
        self.comp.on_mqtt_message(None, None, msg)
        self.assertEqual(h.called, [(self.comp.id, None)])
