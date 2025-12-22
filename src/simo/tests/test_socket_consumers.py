from unittest import mock

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator

from simo.core.models import Gateway, Zone, Component
from simo.users.models import User

from .base import (
    BaseSimoTransactionTestCase,
    mk_instance,
    mk_user,
    mk_role,
    mk_instance_user,
)


class WebsocketConsumersTests(BaseSimoTransactionTestCase):
    def setUp(self):
        super().setUp()
        self.inst_a = mk_instance('inst-a', 'A')
        self.inst_b = mk_instance('inst-b', 'B')
        self.zone_a = Zone.objects.create(instance=self.inst_a, name='Z', order=0)
        self.zone_b = Zone.objects.create(instance=self.inst_b, name='Z', order=0)

    def test_component_controller_throttle_rejects(self):
        from simo.core.socket_consumers import ComponentController
        from simo.generic.controllers import SwitchGroup

        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp = Component.objects.create(
            name='C',
            zone=self.zone_a,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        user = mk_user('u@example.com', 'U')
        role = mk_role(self.inst_a, is_superuser=True)
        mk_instance_user(user, self.inst_a, role, is_active=True)
        user = User.objects.get(pk=user.pk)

        async def run():
            app = ComponentController.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/component-controller/%d/' % comp.id)
            communicator.scope['url_route'] = {'kwargs': {'component_id': str(comp.id)}}
            communicator.scope['user'] = user

            with mock.patch('simo.core.socket_consumers.check_throttle', autospec=True, return_value=1):
                connected, _ = await communicator.connect()
            self.assertFalse(connected)
            await communicator.disconnect()

        async_to_sync(run)()

    def test_component_controller_rejects_user_from_other_instance(self):
        from simo.core.socket_consumers import ComponentController
        from simo.generic.controllers import SwitchGroup

        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp = Component.objects.create(
            name='C',
            zone=self.zone_a,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        user = mk_user('u@example.com', 'U')
        role = mk_role(self.inst_b, is_superuser=True)
        mk_instance_user(user, self.inst_b, role, is_active=True)
        user = User.objects.get(pk=user.pk)

        async def run():
            app = ComponentController.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/component-controller/%d/' % comp.id)
            communicator.scope['url_route'] = {'kwargs': {'component_id': str(comp.id)}}
            communicator.scope['user'] = user

            with mock.patch('simo.core.socket_consumers.check_throttle', autospec=True, return_value=0):
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
                close_msg = await communicator.receive_output(timeout=1)
                self.assertEqual(close_msg.get('type'), 'websocket.close')
            await communicator.disconnect()

        async_to_sync(run)()

    def test_gateway_controller_closes_for_non_superuser(self):
        from simo.core.socket_consumers import GatewayController

        gw = Gateway.objects.create(type='simo.generic.gateways.GenericGatewayHandler')
        user = mk_user('u@example.com', 'U')
        role = mk_role(self.inst_a, is_superuser=False)
        mk_instance_user(user, self.inst_a, role, is_active=True)
        user = User.objects.get(pk=user.pk)

        async def run():
            app = GatewayController.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/gateway-controller/%d/' % gw.id)
            communicator.scope['url_route'] = {'kwargs': {'gateway_id': str(gw.id)}}
            communicator.scope['user'] = user

            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            close_msg = await communicator.receive_output(timeout=1)
            self.assertEqual(close_msg.get('type'), 'websocket.close')
            await communicator.disconnect()

        async_to_sync(run)()

    def test_log_consumer_closes_for_non_superuser(self):
        from simo.core.socket_consumers import LogConsumer
        from simo.generic.controllers import SwitchGroup

        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp = Component.objects.create(
            name='C',
            zone=self.zone_a,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        user = mk_user('su@example.com', 'SU')
        role = mk_role(self.inst_a, is_superuser=True)
        mk_instance_user(user, self.inst_a, role, is_active=True)
        user = User.objects.get(pk=user.pk)

        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(Component)

        async def run():
            app = LogConsumer.as_asgi()
            communicator = WebsocketCommunicator(app, '/ws/log/%d/%d/' % (ct.id, comp.id))
            communicator.scope['url_route'] = {
                'kwargs': {'ct_id': str(ct.id), 'object_pk': str(comp.id)}
            }
            communicator.scope['user'] = user

            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            msg = await communicator.receive_from(timeout=1)
            self.assertIn('INFO', msg)
            await communicator.disconnect()

        # Make a tiny log file and prevent background watcher tasks.
        import tempfile

        with tempfile.NamedTemporaryFile(mode='w+', delete=True) as tmp:
            tmp.write('[INFO] hello\n')
            tmp.flush()

            def _discard_task(coro):
                try:
                    coro.close()
                except Exception:
                    pass
                return mock.Mock()

            with mock.patch('simo.core.socket_consumers.get_log_file_path', autospec=True, return_value=tmp.name), \
                    mock.patch('simo.core.socket_consumers.asyncio.create_task', side_effect=_discard_task):
                async_to_sync(run)()
