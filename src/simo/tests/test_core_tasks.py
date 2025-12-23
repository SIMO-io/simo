from unittest import mock

from django.utils import timezone

from simo.core.models import Gateway, Zone, Component
from simo.users.models import User

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class CoreTasksTests(BaseSimoTestCase):
    def test_component_action_invokes_model_method(self):
        from simo.core.tasks import component_action
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

        with mock.patch('simo.core.tasks.Component.disarm', autospec=True) as disarm:
            component_action(comp.id, 'disarm', args=[], kwargs={})
        disarm.assert_called_once()

    def test_component_action_defaults_args_kwargs(self):
        from simo.core.tasks import component_action
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

        with mock.patch('simo.core.tasks.Component.disarm', autospec=True) as disarm:
            component_action(comp.id, 'disarm')
        disarm.assert_called_once()

    def test_component_action_rejects_invalid_args_kwargs_shapes(self):
        from simo.core.tasks import component_action
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

        with self.assertRaises(TypeError):
            component_action(comp.id, 'disarm', args='nope', kwargs={})
        with self.assertRaises(TypeError):
            component_action(comp.id, 'disarm', args=[], kwargs='nope')

    def test_drop_fingerprints_learn_clears_expired_flags(self):
        from simo.core.tasks import drop_fingerprints_learn

        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)

        inst.learn_fingerprints = user
        inst.learn_fingerprints_start = timezone.now() - timezone.timedelta(minutes=10)
        inst.save(update_fields=['learn_fingerprints', 'learn_fingerprints_start'])

        drop_fingerprints_learn()

        inst.refresh_from_db()
        self.assertIsNone(inst.learn_fingerprints)
        self.assertIsNone(inst.learn_fingerprints_start)

    def test_time_out_discoveries_calls_finish(self):
        from simo.core.tasks import time_out_discoveries

        gw = Gateway.objects.create(
            type='simo.generic.gateways.GenericGatewayHandler',
            discovery={'start': 1, 'timeout': 1, 'controller_uid': 'x', 'init_data': {}, 'result': []},
        )

        with mock.patch('simo.core.models.Gateway.finish_discovery', autospec=True) as finish, \
                mock.patch('simo.core.tasks.time.time', autospec=True, return_value=10):
            time_out_discoveries()
        finish.assert_called_once_with(gw)

    def test_maybe_update_to_latest_returns_signature_when_no_instances(self):
        from simo.core.tasks import maybe_update_to_latest

        ds = {
            'core__latest_version_available': '',
            'core__auto_update': False,
        }

        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = {
            'releases': {
                '1.0.0': {},
                '1.0.1': {},
            }
        }

        with mock.patch('simo.core.tasks.requests.get', autospec=True, return_value=resp), \
                mock.patch('simo.conf.dynamic_settings', ds), \
                mock.patch('simo.core.tasks.pkg_resources.get_distribution', autospec=True, return_value=mock.Mock(version='1.0.0')), \
                mock.patch('simo.core.models.Instance.objects.all', autospec=True) as all_qs, \
                mock.patch('simo.core.tasks.update.s', autospec=True, return_value='sig'):
            all_qs.return_value.count.return_value = 0
            out = maybe_update_to_latest()

        self.assertEqual(ds['core__latest_version_available'], '1.0.1')
        self.assertEqual(out, 'sig')
