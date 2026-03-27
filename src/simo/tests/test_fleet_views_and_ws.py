import json
from unittest import mock

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import Client

from simo.core.models import Component, Gateway, Zone
from simo.fleet.gateways import FleetGatewayHandler
from simo.fleet.models import Colonel
from simo.users.models import User

from .base import BaseSimoTestCase, BaseSimoTransactionTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class FleetViewsTests(BaseSimoTestCase):
    def test_colonels_ping(self):
        client = Client()
        resp = client.get('/fleet/colonels-ping/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'pong')

    def test_new_sentinel_requires_auth(self):
        client = Client()
        resp = client.post('/fleet/new-sentinel/', data=b'{}', content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_new_sentinel_happy_path_returns_component_ids(self):
        inst = mk_instance('inst-a', 'A')
        # Ensure fleet options exist and are loaded.
        inst.refresh_from_db()

        master = mk_user('m@example.com', 'M', is_master=True)
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(master, inst, role, is_active=True)
        master = User.objects.get(pk=master.pk)

        Colonel.objects.create(instance=inst, uid='c-1', type='sentinel', name='S')

        class _FakeForm:
            def __init__(self, data=None):
                self.data = data or {}
                self.errors = {}

            def is_valid(self):
                return True

            def save(self):
                return None

        payload = {
            'instance': inst.uid,
            'zone': 'Z',
            'uid': 'c-1',
            'name': 'Sentinel',
            'voice': 'male',
            'language': 'en',
        }

        client = Client()
        client.force_login(master)
        with mock.patch('simo.fleet.views.SentinelDeviceConfigForm', _FakeForm), \
                mock.patch('simo.fleet.views.time.sleep', autospec=True):
            resp = client.post(
                '/fleet/new-sentinel/',
                data=json.dumps(payload).encode(),
                content_type='application/json',
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_sentinel_form_binds_presence_sensor_to_security_alarm_group(self):
        from simo.fleet.forms import SentinelDeviceConfigForm
        from simo.generic.controllers import AlarmGroup

        inst = mk_instance('inst-b', 'B')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        generic_gw, _ = Gateway.objects.get_or_create(
            type='simo.generic.gateways.GenericGatewayHandler'
        )
        colonel = Colonel.objects.create(
            instance=inst,
            uid='sentinel-1',
            type='sentinel',
            name='S',
            firmware_version='1.0',
            enabled=True,
        )
        alarm_group = Component.objects.create(
            name='Security',
            zone=zone,
            category=None,
            gateway=generic_gw,
            base_type='alarm-group',
            controller_uid=AlarmGroup.uid,
            alarm_category='security',
            config={'is_main': True, 'components': [], 'breach_events': []},
            meta={'breach_times': [], 'events_triggered': []},
            value='disarmed',
        )

        form = SentinelDeviceConfigForm(data={
            'name': 'Sentinel',
            'zone': str(zone.id),
            'colonel': str(colonel.id),
            'assistant': 'alora',
            'language': 'en',
        })
        self.assertTrue(form.is_valid(), form.errors)

        form.save()

        presence_sensor = Component.objects.get(
            zone=zone,
            controller_uid='simo.fleet.controllers.RoomPresenceSensor',
        )
        self.assertEqual(presence_sensor.config.get('sens'), 10)

        alarm_group.refresh_from_db()
        self.assertIn(presence_sensor.id, alarm_group.config.get('components', []))


class FleetConsumerWsTests(BaseSimoTransactionTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.inst.refresh_from_db()
        self.instance_secret = self.inst.fleet_options.secret_key
        # Ensure Fleet gateway exists so FleetConsumer doesn't crash before auth checks.
        Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)

    def test_rejects_missing_instance_uid_header(self):
        from simo.fleet.socket_consumers import FleetConsumer

        async def run():
            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = []
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            close_msg = await communicator.receive_output(timeout=1)
            self.assertEqual(close_msg.get('type'), 'websocket.close')
            await communicator.disconnect()

        async_to_sync(run)()

    def test_rejects_bad_instance_secret(self):
        from simo.fleet.socket_consumers import FleetConsumer

        async def run():
            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = [
                (b'instance-uid', self.inst.uid.encode()),
                (b'instance-secret', b'bad'),
                (b'colonel-uid', b'c-1'),
                (b'colonel-type', b'sentinel'),
                (b'firmware-version', b'1.0'),
                (b'colonel-name', b'C'),
            ]
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            close_msg = await communicator.receive_output(timeout=1)
            self.assertEqual(close_msg.get('type'), 'websocket.close')
            await communicator.disconnect()

        async_to_sync(run)()

    def test_auth_success_but_mqtt_connect_fails_closes(self):
        from simo.fleet.socket_consumers import FleetConsumer

        async def run():
            app = FleetConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/fleet/')
            communicator.scope['headers'] = [
                (b'instance-uid', self.inst.uid.encode()),
                (b'instance-secret', self.instance_secret.encode()),
                (b'colonel-uid', b'c-1'),
                (b'colonel-type', b'sentinel'),
                (b'firmware-version', b'1.0'),
                (b'colonel-name', b'C'),
            ]
            with mock.patch('simo.fleet.socket_consumers.connect_with_retry', autospec=True, return_value=False):
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
                close_msg = await communicator.receive_output(timeout=2)
                self.assertEqual(close_msg.get('type'), 'websocket.close')
            await communicator.disconnect()

        async_to_sync(run)()
