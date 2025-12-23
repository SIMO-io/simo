from __future__ import annotations

import json
from unittest import mock

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTransactionTestCase, mk_instance


class TestSocketConsumersMore(BaseSimoTransactionTestCase):
    def test_component_controller_rejects_anonymous_with_reason(self):
        from simo.core.socket_consumers import ComponentController
        from simo.generic.controllers import SwitchGroup

        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp = Component.objects.create(
            name='C',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        async def run():
            app = ComponentController.as_asgi()
            communicator = WebsocketCommunicator(app, f'/ws/component-controller/{comp.id}/')
            communicator.scope['url_route'] = {'kwargs': {'component_id': str(comp.id)}}
            communicator.scope['user'] = AnonymousUser()

            with mock.patch('simo.core.socket_consumers.check_throttle', autospec=True, return_value=0):
                connected, _ = await communicator.connect()
            self.assertTrue(connected)

            msg = await communicator.receive_from(timeout=1)
            self.assertEqual(json.loads(msg), {'event': 'close', 'reason': 'auth'})

            close_msg = await communicator.receive_output(timeout=1)
            self.assertEqual(close_msg.get('type'), 'websocket.close')

            await communicator.disconnect()

        async_to_sync(run)()

    def test_gateway_controller_disconnect_stops_mqtt(self):
        from simo.core.socket_consumers import GatewayController

        consumer = GatewayController()
        consumer._mqtt_client = mock.Mock()
        consumer._mqtt_stop_event = mock.Mock()

        consumer.disconnect(console_log=None)

        consumer._mqtt_stop_event.set.assert_called_once()
        consumer._mqtt_client.loop_stop.assert_called_once()
        consumer._mqtt_client.disconnect.assert_called_once()

    def test_component_controller_disconnect_stops_mqtt(self):
        from simo.core.socket_consumers import ComponentController

        consumer = ComponentController()
        consumer._mqtt_client = mock.Mock()
        consumer._mqtt_stop_event = mock.Mock()
        consumer.component = 'C'

        consumer.disconnect(console_log=None)

        consumer._mqtt_stop_event.set.assert_called_once()
        consumer._mqtt_client.loop_stop.assert_called_once()
        consumer._mqtt_client.disconnect.assert_called_once()

