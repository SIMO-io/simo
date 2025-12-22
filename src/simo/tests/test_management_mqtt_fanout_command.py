import json
from types import SimpleNamespace
from unittest import mock

from django.contrib.contenttypes.models import ContentType

from simo.core.models import Category, Component, Gateway, Zone
from simo.users.models import ComponentPermission

from .base import BaseSimoTestCase, mk_instance, mk_role, mk_user, mk_instance_user


class ManagementMqttFanoutCommandTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

    def _mk_cmd(self):
        from simo.core.management.commands.run_app_mqtt_fanout import Command

        return Command()

    def test_handle_exits_when_connect_fails(self):
        from simo.core.management.commands.run_app_mqtt_fanout import Command

        cmd = Command()
        with (
            mock.patch('simo.core.management.commands.run_app_mqtt_fanout.connect_with_retry', autospec=True, return_value=False),
            mock.patch('simo.core.management.commands.run_app_mqtt_fanout.install_reconnect_handler', autospec=True),
            mock.patch('simo.core.management.commands.run_app_mqtt_fanout.mqtt.Client', autospec=True),
        ):
            cmd.handle()

    def test_on_connect_subscribes_obj_state(self):
        from simo.core.management.commands.run_app_mqtt_fanout import OBJ_STATE_PREFIX

        cmd = self._mk_cmd()
        client = mock.Mock()
        cmd.on_connect(client, None, None, 0)
        client.subscribe.assert_called_once_with(f'{OBJ_STATE_PREFIX}/#')

    def test_on_message_ignores_bad_topic(self):
        cmd = self._mk_cmd()
        client = mock.Mock()
        cmd.on_message(client, None, SimpleNamespace(topic='nope', payload=b'{}'))
        client.publish.assert_not_called()

    def test_on_message_ignores_unhandled_model(self):
        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(topic=f'SIMO/obj-state/{self.inst.uid}/Other/1', payload=b'{}')
        cmd.on_message(client, None, msg)
        client.publish.assert_not_called()

    def test_on_message_component_missing_obj_is_ignored(self):
        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/obj-state/{self.inst.uid}/Component/1',
            payload=json.dumps({'obj_ct_pk': 999, 'obj_pk': 1}).encode(),
        )
        cmd.on_message(client, None, msg)
        client.publish.assert_not_called()

    def test_on_message_zone_publishes_to_all_instance_users(self):
        master = mk_user('m@example.com', 'M', is_master=True)
        user = mk_user('u@example.com', 'U', is_master=False)
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(user, self.inst, role, is_active=True)
        zone = self.zone

        cmd = self._mk_cmd()
        client = mock.Mock()
        ct_id = ContentType.objects.get_for_model(Zone).pk
        msg = SimpleNamespace(
            topic=f'SIMO/obj-state/{self.inst.uid}/Zone/{zone.id}',
            payload=json.dumps({'obj_ct_pk': ct_id, 'obj_pk': zone.id}).encode(),
        )
        cmd.on_message(client, None, msg)
        published_to = {c.args[0] for c in client.publish.call_args_list}
        self.assertIn(f'SIMO/user/{master.id}/feed/{self.inst.uid}/Zone/{zone.id}', published_to)
        self.assertIn(f'SIMO/user/{user.id}/feed/{self.inst.uid}/Zone/{zone.id}', published_to)

    def test_on_message_component_publishes_to_masters_and_superusers(self):
        master = mk_user('m@example.com', 'M', is_master=True)
        su = mk_user('su@example.com', 'SU', is_master=False)
        role_su = mk_role(self.inst, is_superuser=True)
        mk_instance_user(su, self.inst, role_su, is_active=True)

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
        ct_id = ContentType.objects.get_for_model(Component).pk

        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/obj-state/{self.inst.uid}/Component/{comp.id}',
            payload=json.dumps({'obj_ct_pk': ct_id, 'obj_pk': comp.id}).encode(),
        )
        cmd.on_message(client, None, msg)
        published_to = {c.args[0] for c in client.publish.call_args_list}
        self.assertIn(f'SIMO/user/{master.id}/feed/{self.inst.uid}/Component/{comp.id}', published_to)
        self.assertIn(f'SIMO/user/{su.id}/feed/{self.inst.uid}/Component/{comp.id}', published_to)

    def test_on_message_component_requires_read_permission_for_regular_users(self):
        master = mk_user('m@example.com', 'M', is_master=True)
        user_ok = mk_user('u@example.com', 'U', is_master=False)
        user_no = mk_user('n@example.com', 'N', is_master=False)
        role_ok = mk_role(self.inst, is_superuser=False)
        role_no = mk_role(self.inst, is_superuser=False)
        mk_instance_user(user_ok, self.inst, role_ok, is_active=True)
        mk_instance_user(user_no, self.inst, role_no, is_active=True)

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
        ComponentPermission.objects.filter(role=role_ok, component=comp).update(read=True)
        ComponentPermission.objects.filter(role=role_no, component=comp).update(read=False)
        ct_id = ContentType.objects.get_for_model(Component).pk

        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(
            topic=f'SIMO/obj-state/{self.inst.uid}/Component/{comp.id}',
            payload=json.dumps({'obj_ct_pk': ct_id, 'obj_pk': comp.id}).encode(),
        )
        cmd.on_message(client, None, msg)
        published_to = {c.args[0] for c in client.publish.call_args_list}
        self.assertIn(f'SIMO/user/{master.id}/feed/{self.inst.uid}/Component/{comp.id}', published_to)
        self.assertIn(f'SIMO/user/{user_ok.id}/feed/{self.inst.uid}/Component/{comp.id}', published_to)
        self.assertNotIn(f'SIMO/user/{user_no.id}/feed/{self.inst.uid}/Component/{comp.id}', published_to)

    def test_on_message_handles_invalid_json_without_crash(self):
        cmd = self._mk_cmd()
        client = mock.Mock()
        msg = SimpleNamespace(topic=f'SIMO/obj-state/{self.inst.uid}/Zone/1', payload=b'nope')
        cmd.on_message(client, None, msg)

