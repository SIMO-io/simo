import json
from types import SimpleNamespace
from unittest import mock

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance, mk_role, mk_user, mk_instance_user


class ManagementMqttControlCommandTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

    def _mk_cmd(self):
        from simo.core.management.commands.run_app_mqtt_control import Command

        return Command()

    def test_handle_exits_when_connect_fails(self):
        from simo.core.management.commands.run_app_mqtt_control import Command

        cmd = Command()
        with (
            mock.patch('simo.core.management.commands.run_app_mqtt_control.connect_with_retry', autospec=True, return_value=False),
            mock.patch('simo.core.management.commands.run_app_mqtt_control.install_reconnect_handler', autospec=True),
            mock.patch('simo.core.management.commands.run_app_mqtt_control.mqtt.Client', autospec=True),
        ):
            cmd.handle()

    def test_on_connect_subscribes_control_prefix(self):
        from simo.core.management.commands.run_app_mqtt_control import CONTROL_PREFIX

        cmd = self._mk_cmd()
        client = mock.Mock()
        cmd.on_connect(client, None, None, 0)
        client.subscribe.assert_called_once_with(f'{CONTROL_PREFIX}/+/control/#')

    def test_on_message_ignores_bad_topic(self):
        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(topic='nope', payload=b'{}')
        cmd.on_message(client, None, msg)
        client.publish.assert_not_called()

    def test_on_message_ignores_non_component_path(self):
        user = mk_user('u@example.com', 'U', is_master=True)
        cmd = self._mk_cmd()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Zone/1',
            payload=b'{}',
        )
        cmd.on_message(mock.Mock(), None, msg)

    def test_on_message_ignores_invalid_component_id(self):
        user = mk_user('u@example.com', 'U', is_master=True)
        cmd = self._mk_cmd()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Component/nope',
            payload=b'{}',
        )
        cmd.on_message(mock.Mock(), None, msg)

    def test_on_message_ignores_inactive_user(self):
        user = mk_user('u@example.com', 'U', is_master=False)
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(user, self.inst, role, is_active=False)

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

        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Component/{comp.id}',
            payload=json.dumps({'request_id': 'r', 'method': 'toggle'}).encode(),
        )
        cmd.on_message(client, None, msg)
        client.publish.assert_not_called()

    def test_on_message_throttled_drops_request(self):
        user = mk_user('u@example.com', 'U', is_master=True)
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

        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Component/{comp.id}',
            payload=json.dumps({'request_id': 'r', 'method': 'toggle'}).encode(),
        )
        with mock.patch('simo.core.management.commands.run_app_mqtt_control.check_throttle', autospec=True, return_value=1):
            cmd.on_message(client, None, msg)
        client.publish.assert_not_called()

    def test_on_message_non_master_requires_instance_membership(self):
        user = mk_user('u@example.com', 'U', is_master=False)
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
        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Component/{comp.id}',
            payload=json.dumps({'request_id': 'r', 'method': 'toggle'}).encode(),
        )
        with mock.patch('simo.core.management.commands.run_app_mqtt_control.check_throttle', autospec=True, return_value=0):
            cmd.on_message(client, None, msg)
        client.publish.assert_not_called()

    def test_on_message_non_master_requires_write_permission(self):
        user = mk_user('u@example.com', 'U', is_master=False)
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(user, self.inst, role, is_active=True)

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

        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Component/{comp.id}',
            payload=json.dumps({'request_id': 'r', 'method': 'toggle'}).encode(),
        )
        with mock.patch('simo.core.management.commands.run_app_mqtt_control.check_throttle', autospec=True, return_value=0):
            cmd.on_message(client, None, msg)
        client.publish.assert_not_called()

    def test_on_message_ignores_private_method(self):
        user = mk_user('u@example.com', 'U', is_master=True)
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
        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Component/{comp.id}',
            payload=json.dumps({'request_id': 'r', 'method': '_secret'}).encode(),
        )
        with mock.patch('simo.core.management.commands.run_app_mqtt_control.check_throttle', autospec=True, return_value=0):
            cmd.on_message(client, None, msg)
        client.publish.assert_not_called()

    def test_on_message_method_not_allowed_responds_error(self):
        from simo.generic.controllers import SwitchGroup

        user = mk_user('u@example.com', 'U', is_master=True)
        comp = Component.objects.create(
            name='C',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Component/{comp.id}',
            payload=json.dumps({'request_id': 'r', 'method': 'nope'}).encode(),
        )
        with (
            mock.patch('simo.core.management.commands.run_app_mqtt_control.check_throttle', autospec=True, return_value=0),
            mock.patch('simo.core.management.commands.run_app_mqtt_control.introduce_user', autospec=True),
        ):
            cmd.on_message(client, None, msg)
        self.assertTrue(client.publish.called)

    def test_on_message_success_calls_method_and_responds(self):
        from simo.generic.controllers import SwitchGroup

        user = mk_user('u@example.com', 'U', is_master=True)
        comp = Component.objects.create(
            name='C',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Component/{comp.id}',
            payload=json.dumps({'request_id': 'r', 'method': 'toggle'}).encode(),
        )
        with (
            mock.patch('simo.core.management.commands.run_app_mqtt_control.check_throttle', autospec=True, return_value=0),
            mock.patch('simo.core.management.commands.run_app_mqtt_control.introduce_user', autospec=True),
            mock.patch('simo.core.controllers.Switch.toggle', autospec=True, return_value=None),
        ):
            cmd.on_message(client, None, msg)

        client.publish.assert_called_once()
        payload = json.loads(client.publish.call_args.args[1])
        self.assertTrue(payload['ok'])

    def test_on_message_invalid_json_payload_does_not_crash(self):
        user = mk_user('u@example.com', 'U', is_master=True)
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
        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Component/{comp.id}',
            payload=b'nope',
        )
        cmd.on_message(client, None, msg)
        client.publish.assert_not_called()

    def test_on_message_subcomponent_targets_slave(self):
        from simo.generic.controllers import SwitchGroup

        user = mk_user('u@example.com', 'U', is_master=True)
        master = Component.objects.create(
            name='M',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        slave = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        master.slaves.add(slave)

        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/user/{user.id}/control/{self.inst.uid}/Component/{master.id}',
            payload=json.dumps({'request_id': 'r', 'method': 'toggle', 'subcomponent_id': slave.id}).encode(),
        )
        with (
            mock.patch('simo.core.management.commands.run_app_mqtt_control.check_throttle', autospec=True, return_value=0),
            mock.patch('simo.core.management.commands.run_app_mqtt_control.introduce_user', autospec=True),
            mock.patch('simo.core.controllers.Switch.toggle', autospec=True, return_value=None) as toggle,
        ):
            cmd.on_message(client, None, msg)

        toggle.assert_called_once()
        client.publish.assert_called_once()

    def test_respond_without_request_id_does_not_publish(self):
        cmd = self._mk_cmd()
        client = mock.Mock()
        cmd.respond(client, 1, request_id=None, ok=True, result=1)
        client.publish.assert_not_called()
