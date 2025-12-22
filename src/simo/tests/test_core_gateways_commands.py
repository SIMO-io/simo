import json
from unittest import mock

from django.contrib.contenttypes.models import ContentType

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance, mk_user


class FakeMqttClient:
    def __init__(self):
        self.on_connect = None
        self.on_message = None
        self.subscribed = []

    def username_pw_set(self, *_args, **_kwargs):
        return None

    def reconnect_delay_set(self, **_kwargs):
        return None

    def subscribe(self, topic):
        self.subscribed.append(topic)


from simo.core.gateways import BaseObjectCommandsGatewayHandler


class TestGatewayHandler(BaseObjectCommandsGatewayHandler):
    name = 'Dummy'
    config_form = object()

    def perform_value_send(self, component, value):
        raise NotImplementedError


class GatewaysCommandHandlingTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.DummyGatewayHandler')
        self.ct_id = ContentType.objects.get_for_model(Component).pk

    def _mk_handler(self):
        with mock.patch('simo.core.gateways.mqtt.Client', autospec=True, side_effect=FakeMqttClient):
            handler = TestGatewayHandler(self.gw)
        handler.logger = mock.Mock()
        return handler

    def test_gateway_handler_uid_is_module_and_class(self):
        from simo.core.gateways import BaseGatewayHandler

        class X(BaseGatewayHandler):
            name = 'X'
            config_form = object()

        self.assertIn('X', X.uid)
        self.assertIn('test_core_gateways_commands', X.uid)

    def test_on_mqtt_connect_subscribes_to_gateway_topic(self):
        from simo.core.events import GatewayObjectCommand

        handler = self._mk_handler()
        handler._on_mqtt_connect(handler.mqtt_client, None, None, 0)

        expected = GatewayObjectCommand(self.gw).get_topic()
        self.assertEqual(handler.mqtt_client.subscribed, [expected])

    def test_on_mqtt_message_ignores_missing_component(self):
        handler = self._mk_handler()
        handler.perform_value_send = mock.Mock()

        msg = mock.Mock()
        msg.payload = json.dumps({'obj_ct_pk': self.ct_id, 'obj_pk': 99999, 'set_val': True}).encode()
        handler._on_mqtt_message(None, None, msg)

        handler.perform_value_send.assert_not_called()

    def test_on_mqtt_message_set_val_calls_perform_value_send(self):
        handler = self._mk_handler()
        handler.perform_value_send = mock.Mock()

        comp = Component.objects.create(
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

        msg = mock.Mock()
        msg.payload = json.dumps({'obj_ct_pk': self.ct_id, 'obj_pk': comp.pk, 'set_val': True}).encode()
        handler._on_mqtt_message(None, None, msg)

        handler.perform_value_send.assert_called_once()
        self.assertEqual(handler.perform_value_send.call_args.args[0].pk, comp.pk)
        self.assertEqual(handler.perform_value_send.call_args.args[1], True)

    def test_on_mqtt_message_bulk_send_calls_perform_value_send_for_matching_components(self):
        handler = self._mk_handler()
        handler.perform_value_send = mock.Mock()

        c1 = Component.objects.create(
            name='C1',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )
        c2 = Component.objects.create(
            name='C2',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

        msg = mock.Mock()
        msg.payload = json.dumps({'bulk_send': {str(c1.pk): True, str(c2.pk): False, '9999': True}}).encode()
        handler._on_mqtt_message(None, None, msg)

        self.assertEqual(handler.perform_value_send.call_count, 2)
        called_ids = {c.args[0].pk for c in handler.perform_value_send.call_args_list}
        self.assertEqual(called_ids, {c1.pk, c2.pk})

    def test_on_mqtt_message_bulk_send_skips_components_from_other_gateway(self):
        handler = self._mk_handler()
        handler.perform_value_send = mock.Mock()

        other_gw, _ = Gateway.objects.get_or_create(type='test.other.gateway')
        c_other = Component.objects.create(
            name='CO',
            zone=self.zone,
            category=None,
            gateway=other_gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

        msg = mock.Mock()
        msg.payload = json.dumps({'bulk_send': {str(c_other.pk): True}}).encode()
        handler._on_mqtt_message(None, None, msg)

        handler.perform_value_send.assert_not_called()

    def test_on_mqtt_message_actor_id_introduces_user(self):
        handler = self._mk_handler()
        handler.perform_value_send = mock.Mock()

        user = mk_user('u@example.com', 'U')
        comp = Component.objects.create(
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

        msg = mock.Mock()
        msg.payload = json.dumps(
            {'obj_ct_pk': self.ct_id, 'obj_pk': comp.pk, 'set_val': True, 'actor_id': user.pk}
        ).encode()

        with mock.patch('simo.users.utils.introduce_user', autospec=True) as intro:
            handler._on_mqtt_message(None, None, msg)
        intro.assert_called_once()

    def test_perform_bulk_send_continues_on_exceptions(self):
        handler = self._mk_handler()

        c1 = Component.objects.create(
            name='C1',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )
        c2 = Component.objects.create(
            name='C2',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

        handler.perform_value_send = mock.Mock(side_effect=[RuntimeError('boom'), None])
        handler.perform_bulk_send({str(c1.pk): True, str(c2.pk): False})

        self.assertEqual(handler.perform_value_send.call_count, 2)
        handler.logger.error.assert_called()
