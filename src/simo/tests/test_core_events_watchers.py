import json
from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from simo.core.events import ObjectChangeEvent
from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class EventsAndWatchersTests(BaseSimoTestCase):
    def test_object_change_event_publishes_via_shared_hub(self):
        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp = Component.objects.create(
            name='C',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

        hub = mock.Mock()
        with mock.patch('simo.core.events.get_mqtt_hub', autospec=True, return_value=hub):
            evt = ObjectChangeEvent(inst, comp, dirty_fields={'value': True})
            evt.publish(retain=True)

        hub.publish.assert_called_once()

    def test_on_mqtt_message_filters_payloads_and_calls_handler(self):
        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp = Component.objects.create(
            name='C',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

        called = []

        def handler(obj):
            called.append(obj.id)

        comp._on_change_function = handler
        comp._obj_ct_id = ContentType.objects.get_for_model(Component).pk
        now_ts = timezone.now().timestamp()
        comp._on_change_since = now_ts - 1

        msg = mock.Mock()

        # Invalid JSON => ignored
        msg.payload = b'nope'
        comp.on_mqtt_message(None, None, msg)
        self.assertEqual(called, [])

        # Irrelevant dirty_fields => ignored
        msg.payload = json.dumps(
            {'obj_pk': comp.id, 'obj_ct_pk': comp._obj_ct_id, 'dirty_fields': {'meta': 1}, 'timestamp': now_ts}
        ).encode()
        comp.on_mqtt_message(None, None, msg)
        self.assertEqual(called, [])

        # Old timestamp => ignored
        msg.payload = json.dumps(
            {
                'obj_pk': comp.id,
                'obj_ct_pk': comp._obj_ct_id,
                'dirty_fields': {'value': True},
                'timestamp': now_ts - 100,
            }
        ).encode()
        comp.on_mqtt_message(None, None, msg)
        self.assertEqual(called, [])

        # Recent value change => handler called
        msg.payload = json.dumps(
            {
                'obj_pk': comp.id,
                'obj_ct_pk': comp._obj_ct_id,
                'dirty_fields': {'value': True},
                'timestamp': timezone.now().timestamp(),
            }
        ).encode()
        with mock.patch.object(comp, 'refresh_from_db', autospec=True):
            comp.on_mqtt_message(None, None, msg)
        self.assertEqual(called, [comp.id])

    def test_on_change_subscribe_unsubscribe_via_hub(self):
        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp = Component.objects.create(
            name='C',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

        hub = mock.Mock()
        hub.subscribe.side_effect = ['tok1', 'tok2']

        with (
            mock.patch('simo.core.events.get_mqtt_hub', autospec=True, return_value=hub),
            mock.patch.dict('os.environ', {'SIMO_MQTT_WATCHERS_VIA_HUB': '1'}),
        ):
            comp.on_change(lambda _c: None)
            comp.on_change(lambda _c: None)

        self.assertEqual(hub.subscribe.call_count, 2)
        hub.unsubscribe.assert_called_once_with('tok1')
