import asyncio
import json
import threading
import zlib
from types import SimpleNamespace
from unittest import mock

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator

from simo.core.models import Component, Gateway, Zone
from simo.fleet.gateways import FleetGatewayHandler
from simo.fleet.models import Colonel

from .base import BaseSimoTestCase, BaseSimoTransactionTestCase, mk_instance


class FakeMqttClient:
    def __init__(self):
        self.on_connect = None
        self.on_message = None
        self.loop_started = 0
        self.loop_stopped = 0
        self.disconnected = 0

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

    def subscribe(self, *_a, **_k):
        return (0, 1)


def _discard_task(coro):
    try:
        coro.close()
    except Exception:
        pass
    return mock.Mock()


class FleetConsumerWsMoreTests(BaseSimoTransactionTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.inst.refresh_from_db()
        self.secret = self.inst.fleet_options.secret_key
        Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)

    def _mk_headers(self, **overrides):
        headers = {
            'instance-uid': self.inst.uid,
            'instance-secret': self.secret,
            'colonel-uid': 'c-1',
            'colonel-type': 'sentinel',
            'firmware-version': '1.0',
            'colonel-name': 'C',
        }
        headers.update(overrides)
        return [(k.encode(), str(v).encode()) for k, v in headers.items()]

    def test_rejects_unknown_instance_uid_header(self):
        from simo.fleet.socket_consumers import FleetConsumer

        async def run():
            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = self._mk_headers(**{'instance-uid': 'nope'})
            with mock.patch('simo.fleet.socket_consumers.asyncio.create_task', side_effect=_discard_task):
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
                close_msg = await communicator.receive_output(timeout=2)
                self.assertEqual(close_msg.get('type'), 'websocket.close')
            await communicator.disconnect()

        async_to_sync(run)()

    def test_existing_disabled_colonel_is_reenabled_on_connect(self):
        from simo.fleet.socket_consumers import FleetConsumer

        Colonel.objects.create(
            instance=self.inst,
            uid='c-1',
            type='sentinel',
            firmware_version='1.0',
            enabled=False,
        )

        async def run():
            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = self._mk_headers()
            with (
                mock.patch('simo.fleet.socket_consumers.mqtt.Client', autospec=True, return_value=FakeMqttClient()),
                mock.patch('simo.fleet.socket_consumers.install_reconnect_handler', autospec=True),
                mock.patch('simo.fleet.socket_consumers.connect_with_retry', autospec=True, return_value=True),
                mock.patch('simo.fleet.socket_consumers.asyncio.create_task', side_effect=_discard_task),
            ):
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
                msg = await communicator.receive_from(timeout=2)
                self.assertEqual(json.loads(msg), {'command': 'hello'})
            await communicator.disconnect()

        async_to_sync(run)()
        self.assertTrue(Colonel.objects.get(uid='c-1').enabled)

    def test_connect_success_sends_hello(self):
        from simo.fleet.socket_consumers import FleetConsumer

        async def run():
            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = self._mk_headers()

            with (
                mock.patch('simo.fleet.socket_consumers.mqtt.Client', autospec=True, return_value=FakeMqttClient()),
                mock.patch('simo.fleet.socket_consumers.install_reconnect_handler', autospec=True),
                mock.patch('simo.fleet.socket_consumers.connect_with_retry', autospec=True, return_value=True),
                mock.patch('simo.fleet.socket_consumers.asyncio.create_task', side_effect=_discard_task),
            ):
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
                msg = await communicator.receive_from(timeout=2)
                self.assertEqual(json.loads(msg), {'command': 'hello'})
            await communicator.disconnect()

        async_to_sync(run)()

    def test_connect_success_sets_colonel_socket_connected(self):
        from simo.fleet.socket_consumers import FleetConsumer

        async def run():
            from asgiref.sync import sync_to_async

            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = self._mk_headers()

            with (
                mock.patch('simo.fleet.socket_consumers.mqtt.Client', autospec=True, return_value=FakeMqttClient()),
                mock.patch('simo.fleet.socket_consumers.install_reconnect_handler', autospec=True),
                mock.patch('simo.fleet.socket_consumers.connect_with_retry', autospec=True, return_value=True),
                mock.patch('simo.fleet.socket_consumers.asyncio.create_task', side_effect=_discard_task),
            ):
                await communicator.connect()
                await communicator.receive_from(timeout=2)
                # While connected, Colonel row should be marked connected.
                colonel = await sync_to_async(Colonel.objects.get, thread_sensitive=True)(uid='c-1')
                self.assertTrue(colonel.socket_connected)
            await communicator.disconnect()

        async_to_sync(run)()
        # After disconnect, server clears the flag.
        self.assertFalse(Colonel.objects.get(uid='c-1').socket_connected)

    def test_connect_firmware_auto_update_sends_ota_update(self):
        from simo.fleet.socket_consumers import FleetConsumer

        Colonel.objects.create(
            instance=self.inst,
            uid='c-1',
            type='sentinel',
            firmware_version='1.0',
            enabled=True,
            firmware_auto_update=True,
            minor_upgrade_available='1.1',
        )

        async def run():
            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = self._mk_headers()
            with mock.patch('simo.fleet.socket_consumers.asyncio.create_task', side_effect=_discard_task):
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
                msg = await communicator.receive_from(timeout=2)
                self.assertEqual(json.loads(msg), {'command': 'ota_update', 'version': '1.1'})
            await communicator.disconnect()

        async_to_sync(run)()

    def test_receive_get_config_compresses_for_non_sentinel(self):
        from simo.fleet.socket_consumers import FleetConsumer

        async def run():
            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = self._mk_headers(**{'colonel-type': 'ample-wall'})

            with (
                mock.patch('simo.fleet.socket_consumers.mqtt.Client', autospec=True, return_value=FakeMqttClient()),
                mock.patch('simo.fleet.socket_consumers.install_reconnect_handler', autospec=True),
                mock.patch('simo.fleet.socket_consumers.connect_with_retry', autospec=True, return_value=True),
                mock.patch('simo.fleet.socket_consumers.asyncio.create_task', side_effect=_discard_task),
            ):
                await communicator.connect()
                await communicator.receive_from(timeout=2)  # hello
                await communicator.send_to(text_data=json.dumps({'get_config': 1}))
                out = await communicator.receive_output(timeout=2)
                self.assertEqual(out.get('type'), 'websocket.send')
                raw = out.get('bytes')
                payload = json.loads(zlib.decompress(raw).decode())
                self.assertEqual(payload.get('command'), 'set_config')
            await communicator.disconnect()

        async_to_sync(run)()

    def test_receive_comp_options_updates_meta(self):
        from simo.fleet.socket_consumers import FleetConsumer

        zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        comp = Component.objects.create(
            name='X',
            zone=zone,
            category=None,
            gateway=Gateway.objects.get(type=FleetGatewayHandler.uid),
            base_type='switch',
            controller_uid='x',
            config={'colonel': 0},
            meta={},
            value=False,
        )

        async def run():
            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = self._mk_headers()

            with (
                mock.patch('simo.fleet.socket_consumers.mqtt.Client', autospec=True, return_value=FakeMqttClient()),
                mock.patch('simo.fleet.socket_consumers.install_reconnect_handler', autospec=True),
                mock.patch('simo.fleet.socket_consumers.connect_with_retry', autospec=True, return_value=True),
                mock.patch('simo.fleet.socket_consumers.asyncio.create_task', side_effect=_discard_task),
            ):
                await communicator.connect()
                await communicator.receive_from(timeout=2)
                await communicator.send_to(text_data=json.dumps({'comp': comp.id, 'options': {'a': 1}}))
            await communicator.disconnect()

        async_to_sync(run)()
        comp.refresh_from_db()
        self.assertEqual(comp.meta.get('options'), {'a': 1})

    def test_receive_comp_val_calls_receive_from_device(self):
        from simo.fleet.socket_consumers import FleetConsumer
        from simo.fleet.controllers import BinarySensor

        zone = Zone.objects.create(instance=self.inst, name='Z2', order=1)
        comp = Component.objects.create(
            name='AQ',
            zone=zone,
            category=None,
            gateway=Gateway.objects.get(type=FleetGatewayHandler.uid),
            base_type='binary-sensor',
            controller_uid=BinarySensor.uid,
            config={'colonel': 0, 'pin_no': 1},
            meta={},
            value=False,
        )

        async def run():
            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = self._mk_headers()

            called = threading.Event()

            with (
                mock.patch('simo.fleet.socket_consumers.mqtt.Client', autospec=True, return_value=FakeMqttClient()),
                mock.patch('simo.fleet.socket_consumers.install_reconnect_handler', autospec=True),
                mock.patch('simo.fleet.socket_consumers.connect_with_retry', autospec=True, return_value=True),
                mock.patch('simo.fleet.socket_consumers.asyncio.create_task', side_effect=_discard_task),
                mock.patch('simo.core.controllers.ControllerBase._receive_from_device', autospec=True) as recv,
            ):
                recv.side_effect = lambda *_a, **_k: called.set()
                await communicator.connect()
                await communicator.receive_from(timeout=2)
                await communicator.send_to(text_data=json.dumps({'comp': comp.id, 'val': True, 'alive': False, 'error_msg': 'E'}))
                for _ in range(50):
                    if called.is_set():
                        break
                    await asyncio.sleep(0.01)
            await communicator.disconnect()

            self.assertTrue(called.is_set())
            recv.assert_called_once()
            self.assertEqual(recv.call_args.args[1], True)
            self.assertEqual(recv.call_args.args[2], False)
            self.assertIsNone(recv.call_args.args[3])
            self.assertEqual(recv.call_args.args[4], 'E')

        async_to_sync(run)()


class FleetConsumerUnitMoreTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.inst.refresh_from_db()
        self.gw, _ = Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        self.colonel = Colonel.objects.create(
            instance=self.inst,
            uid='c-1',
            type='sentinel',
            firmware_version='1.0',
            enabled=True,
        )

    def test_on_mqtt_message_bulk_send_filters_by_colonel(self):
        from simo.fleet.socket_consumers import FleetConsumer

        c1 = Component.objects.create(
            name='A',
            zone=Zone.objects.create(instance=self.inst, name='Z', order=0),
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={'colonel': self.colonel.id},
            meta={},
            value=False,
        )
        c_other = Component.objects.create(
            name='B',
            zone=c1.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={'colonel': 999},
            meta={},
            value=False,
        )

        consumer = FleetConsumer()
        consumer.colonel = self.colonel
        consumer.send_data = mock.AsyncMock()

        msg = SimpleNamespace(payload=json.dumps({'bulk_send': {str(c1.id): True, str(c_other.id): False}}).encode())
        consumer.on_mqtt_message(None, None, msg)

        consumer.send_data.assert_called_once()
        payload = consumer.send_data.call_args.args[0]
        self.assertEqual(payload['command'], 'bulk_set')
        self.assertEqual(payload['values'], [{'id': c1.id, 'val': True}])

    def test_on_mqtt_message_component_set_val_sends_set_val(self):
        from simo.fleet.socket_consumers import FleetConsumer
        from django.contrib.contenttypes.models import ContentType

        comp = Component.objects.create(
            name='A',
            zone=Zone.objects.create(instance=self.inst, name='Z', order=0),
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={'colonel': self.colonel.id},
            meta={},
            value=False,
        )

        consumer = FleetConsumer()
        consumer.colonel = self.colonel
        consumer.send_data = mock.AsyncMock()

        ct_id = ContentType.objects.get_for_model(Component).pk
        payload = {'obj_ct_pk': ct_id, 'obj_pk': comp.id, 'set_val': True}
        msg = SimpleNamespace(payload=json.dumps(payload).encode())

        consumer.on_mqtt_message(None, None, msg)

        consumer.send_data.assert_called_once_with({'command': 'set_val', 'id': comp.id, 'val': True})

    def test_on_mqtt_message_colonel_update_config_sends_set_config(self):
        from simo.fleet.socket_consumers import FleetConsumer
        from django.contrib.contenttypes.models import ContentType

        consumer = FleetConsumer()
        consumer.colonel = self.colonel
        consumer.instance = self.inst
        consumer.gateway = self.gw
        consumer.send_data = mock.AsyncMock()
        consumer.get_config_data = mock.AsyncMock(return_value={'devices': {}})

        ct_id = ContentType.objects.get_for_model(Colonel).pk
        msg = SimpleNamespace(payload=json.dumps({'obj_ct_pk': ct_id, 'obj_pk': self.colonel.id, 'command': 'update_config'}).encode())

        consumer.on_mqtt_message(None, None, msg)

        consumer.send_data.assert_called_once()
        self.assertEqual(consumer.send_data.call_args.args[0]['command'], 'set_config')

    def test_decode_device_audio_wrong_channel_returns_none(self):
        from simo.fleet.socket_consumers import FleetConsumer, SPK_CHANNEL_ID

        consumer = FleetConsumer()
        frame = bytes([SPK_CHANNEL_ID]) + b'\x00\x00'
        self.assertIsNone(consumer._decode_device_audio(frame))

    def test_decode_device_audio_short_adpcm_returns_none(self):
        from simo.fleet.socket_consumers import FleetConsumer, ADPCM_FRAME_FLAG

        consumer = FleetConsumer()
        frame = bytes([ADPCM_FRAME_FLAG]) + b'\x00' * 2
        self.assertIsNone(consumer._decode_device_audio(frame))

    def test_decode_device_audio_valid_pcm_returns_payload(self):
        from simo.fleet.socket_consumers import FleetConsumer

        consumer = FleetConsumer()
        # MIC channel, raw PCM: total length must be odd and payload even.
        frame = bytes([0]) + b'\x01\x02'
        self.assertEqual(consumer._decode_device_audio(frame), b'\x01\x02')
