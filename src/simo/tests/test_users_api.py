from rest_framework.test import APIClient

from simo.core.models import Zone, Gateway, Component
from simo.users.models import User, ComponentPermission

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


def _results(resp):
    data = resp.json()
    return data.get('results', data)


class UsersViewSetTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')

        self.admin = mk_user('admin@example.com', 'Admin')
        admin_role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.admin, self.inst, admin_role, is_active=True)
        self.admin = User.objects.get(pk=self.admin.pk)

        self.user = mk_user('u@example.com', 'User')
        user_role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(self.user, self.inst, user_role, is_active=True)
        self.user = User.objects.get(pk=self.user.pk)

        self.api = APIClient()
        self.api.force_authenticate(user=self.admin)

    def test_users_list_is_instance_scoped(self):
        resp = self.api.get(f'/api/{self.inst.slug}/users/users/')
        self.assertEqual(resp.status_code, 200)
        ids = {row['id'] for row in _results(resp)}
        self.assertIn(self.admin.id, ids)
        self.assertIn(self.user.id, ids)

    def test_delete_self_is_denied(self):
        api = APIClient()
        api.force_authenticate(user=self.user)
        resp = api.delete(f'/api/{self.inst.slug}/users/users/{self.user.id}/')
        self.assertIn(resp.status_code, (400, 403))

    def test_update_other_user_denied_without_manage_permission(self):
        role = mk_role(self.inst, is_superuser=False, can_manage_users=False)
        actor = mk_user('actor@example.com', 'Actor')
        mk_instance_user(actor, self.inst, role, is_active=True)
        actor = User.objects.get(pk=actor.pk)

        api = APIClient()
        api.force_authenticate(user=actor)
        resp = api.patch(
            f'/api/{self.inst.slug}/users/users/{self.user.id}/',
            data={'is_active': False},
            format='json',
        )
        self.assertIn(resp.status_code, (400, 403))

    def test_superuser_can_deactivate_user(self):
        resp = self.api.patch(
            f'/api/{self.inst.slug}/users/users/{self.user.id}/',
            data={'is_active': False},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.get(pk=self.user.pk).is_active)

    def test_last_superuser_cannot_downgrade_self(self):
        # Ensure admin is the only superuser in this instance.
        self.api.force_authenticate(user=self.admin)
        non_super_role = mk_role(self.inst, is_superuser=False)
        resp = self.api.patch(
            f'/api/{self.inst.slug}/users/users/{self.admin.id}/',
            data={'role': non_super_role.id},
            format='multipart',
        )
        self.assertIn(resp.status_code, (400, 403))


class ComponentPermissionsViewSetTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        from simo.generic.controllers import SwitchGroup

        self.comp = Component.objects.create(
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

        # Only master users are guaranteed to pass the current viewset logic.
        self.master = mk_user('m@example.com', 'M', is_master=True)
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.master, self.inst, role, is_active=True)
        self.master = User.objects.get(pk=self.master.pk)

        self.role = mk_role(self.inst, is_superuser=False)

        # Ensure we have an explicit permission row to update.
        ComponentPermission.objects.filter(role=self.role, component=self.comp).delete()
        self.cp = ComponentPermission.objects.create(role=self.role, component=self.comp, read=False, write=False)

    def test_master_can_update_component_permissions(self):
        api = APIClient()
        api.force_authenticate(user=self.master)
        resp = api.patch(
            f'/api/{self.inst.slug}/users/componentpermissions/{self.cp.id}/',
            data={'read': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.cp.refresh_from_db()
        self.assertTrue(self.cp.read)


class DeviceReportEndpointTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.user = mk_user('u@example.com', 'U')
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(self.user, self.inst, role, is_active=True)
        self.user = User.objects.get(pk=self.user.pk)
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

    def test_device_report_requires_token_and_os(self):
        resp = self.api.post(
            f'/api/{self.inst.slug}/users/device-report/',
            data={},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

        resp = self.api.post(
            f'/api/{self.inst.slug}/users/device-report/',
            data={'device_token': 't'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
