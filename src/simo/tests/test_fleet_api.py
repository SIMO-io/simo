import json
from unittest import mock

from rest_framework.test import APIClient

from simo.core.models import Zone, Gateway, Component
from simo.fleet.models import Colonel
from simo.users.models import User

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class FleetColonelsApiTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')

        self.superuser = mk_user('su@example.com', 'SU')
        su_role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.superuser, self.inst, su_role, is_active=True)
        self.superuser = User.objects.get(pk=self.superuser.pk)

        self.regular = mk_user('u@example.com', 'U')
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(self.regular, self.inst, role, is_active=True)
        self.regular = User.objects.get(pk=self.regular.pk)

        self.colonel = Colonel.objects.create(instance=self.inst, uid='c-1', name='C1')

    def test_colonels_list_requires_superuser(self):
        api = APIClient()
        api.force_authenticate(user=self.regular)
        resp = api.get(f'/api/{self.inst.slug}/fleet/colonels/')
        self.assertEqual(resp.status_code, 403)

    def test_colonels_list_works_for_superuser(self):
        api = APIClient()
        api.force_authenticate(user=self.superuser)
        resp = api.get(f'/api/{self.inst.slug}/fleet/colonels/')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in resp.json().get('results', [])]
        self.assertIn(self.colonel.id, ids)

    def test_colonel_actions_call_model_methods(self):
        api = APIClient()
        api.force_authenticate(user=self.superuser)

        with mock.patch.object(Colonel, 'check_for_upgrade', autospec=True) as chk:
            resp = api.post(f'/api/{self.inst.slug}/fleet/colonels/{self.colonel.id}/check_for_upgrade/')
        self.assertEqual(resp.status_code, 200)
        chk.assert_called_once()

        with mock.patch.object(Colonel, 'restart', autospec=True) as restart:
            resp = api.post(f'/api/{self.inst.slug}/fleet/colonels/{self.colonel.id}/restart/')
        self.assertEqual(resp.status_code, 200)
        restart.assert_called_once()

        with mock.patch.object(Colonel, 'update_config', autospec=True) as upd:
            resp = api.post(f'/api/{self.inst.slug}/fleet/colonels/{self.colonel.id}/update_config/')
        self.assertEqual(resp.status_code, 200)
        upd.assert_called_once()

    def test_colonel_upgrade_calls_update_firmware(self):
        api = APIClient()
        api.force_authenticate(user=self.superuser)
        self.colonel.major_upgrade_available = '2.0'
        self.colonel.save(update_fields=['major_upgrade_available'])

        with mock.patch.object(Colonel, 'update_firmware', autospec=True) as upd:
            resp = api.post(f'/api/{self.inst.slug}/fleet/colonels/{self.colonel.id}/upgrade/')
        self.assertEqual(resp.status_code, 200)
        upd.assert_called_once()

    def test_colonel_move_to_validates_target(self):
        api = APIClient()
        api.force_authenticate(user=self.superuser)

        # Wrong type => invalid target.
        wrong = Colonel.objects.create(instance=self.inst, uid='c-wrong', name='Wrong', type='sentinel')
        with mock.patch.object(Colonel, 'move_to', autospec=True) as move_to:
            resp = api.post(
                f'/api/{self.inst.slug}/fleet/colonels/{self.colonel.id}/move_to/',
                data=json.dumps({'target': wrong.id}).encode(),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 400)
        move_to.assert_not_called()

        # Valid target.
        target = Colonel.objects.create(instance=self.inst, uid='c-2', name='C2', type=self.colonel.type)
        with mock.patch.object(Colonel, 'move_to', autospec=True) as move_to:
            resp = api.post(
                f'/api/{self.inst.slug}/fleet/colonels/{self.colonel.id}/move_to/',
                data=json.dumps({'target': target.id}).encode(),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200)
        move_to.assert_called_once()

    def test_colonel_delete_denied_when_has_components(self):
        zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        from simo.generic.controllers import SwitchGroup

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
        self.colonel.components.add(comp)

        api = APIClient()
        api.force_authenticate(user=self.superuser)
        resp = api.delete(f'/api/{self.inst.slug}/fleet/colonels/{self.colonel.id}/')
        self.assertEqual(resp.status_code, 400)

