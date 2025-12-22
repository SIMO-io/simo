import datetime
from unittest import mock

from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from simo.users.models import InstanceInvitation, Fingerprint, User

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


def _results(resp):
    data = resp.json()
    return data.get('results', data)


class InvitationsApiTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')

        self.manager = mk_user('mgr@example.com', 'Mgr')
        role_mgr = mk_role(self.inst, can_manage_users=True)
        mk_instance_user(self.manager, self.inst, role_mgr, is_active=True)
        self.manager = User.objects.get(pk=self.manager.pk)

        self.denied = mk_user('u@example.com', 'U')
        role_denied = mk_role(self.inst, can_manage_users=False)
        mk_instance_user(self.denied, self.inst, role_denied, is_active=True)
        self.denied = User.objects.get(pk=self.denied.pk)

        # Default role used by create()
        self.default_role = mk_role(self.inst, is_default=True)

    def test_invitations_list_requires_manage_users(self):
        inv = InstanceInvitation.objects.create(
            instance=self.inst,
            role=self.default_role,
            to_email='x@example.com',
        )

        api = APIClient()
        api.force_authenticate(user=self.denied)
        resp = api.get(f'/api/{self.inst.slug}/users/invitations/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('results'), [])

        api = APIClient()
        api.force_authenticate(user=self.manager)
        resp = api.get(f'/api/{self.inst.slug}/users/invitations/')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in _results(resp)]
        self.assertIn(inv.id, ids)

    def test_invitation_create_picks_default_role(self):
        api = APIClient()
        api.force_authenticate(user=self.manager)
        resp = api.post(
            f'/api/{self.inst.slug}/users/invitations/',
            data={'to_email': 'new@example.com'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        inv_id = resp.json()['id']
        inv = InstanceInvitation.objects.get(id=inv_id)
        self.assertEqual(inv.instance_id, self.inst.id)
        self.assertEqual(inv.from_user_id, self.manager.id)
        self.assertEqual(inv.role_id, self.default_role.id)

    def test_invitation_send_action_returns_error_on_bad_response(self):
        inv = InstanceInvitation.objects.create(
            instance=self.inst,
            role=self.default_role,
            from_user=self.manager,
            to_email='x@example.com',
        )

        api = APIClient()
        api.force_authenticate(user=self.manager)
        with mock.patch.object(InstanceInvitation, 'send', autospec=True, return_value=None):
            resp = api.post(f'/api/{self.inst.slug}/users/invitations/{inv.id}/send/')
        self.assertEqual(resp.status_code, 400)


class AcceptInvitationViewTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.actor = mk_user('a@example.com', 'A')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.actor, self.inst, role, is_active=True)
        self.actor = User.objects.get(pk=self.actor.pk)

    def test_accept_invitation_returns_need_login_json_for_app(self):
        role = mk_role(self.inst, is_default=True)
        inv = InstanceInvitation.objects.create(
            instance=self.inst,
            role=role,
            to_email='x@example.com',
            expire_date=timezone.now() + datetime.timedelta(days=1),
        )

        client = Client()
        resp = client.get(
            f'/users/accept-invitation/{inv.token}/',
            HTTP_USER_AGENT='SIMO/1.0',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'need-login')
        self.assertIn('redirect', resp.json())

    def test_accept_invitation_expired_returns_error_json_for_app(self):
        role = mk_role(self.inst, is_default=True)
        inv = InstanceInvitation.objects.create(
            instance=self.inst,
            role=role,
            to_email='x@example.com',
            expire_date=timezone.now() - datetime.timedelta(days=1),
        )

        client = Client()
        resp = client.get(
            f'/users/accept-invitation/{inv.token}/',
            HTTP_USER_AGENT='SIMO/1.0',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'error')

    def test_accept_invitation_taken_returns_error_json_for_app(self):
        role = mk_role(self.inst, is_default=True)
        inv = InstanceInvitation.objects.create(
            instance=self.inst,
            role=role,
            to_email='x@example.com',
            expire_date=timezone.now() + datetime.timedelta(days=1),
            taken_by=self.actor,
        )

        client = Client()
        resp = client.get(
            f'/users/accept-invitation/{inv.token}/',
            HTTP_USER_AGENT='SIMO/1.0',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'error')


class FingerprintsApiTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')

        self.manager = mk_user('mgr@example.com', 'Mgr')
        role_mgr = mk_role(self.inst, can_manage_users=True)
        mk_instance_user(self.manager, self.inst, role_mgr, is_active=True)
        self.manager = User.objects.get(pk=self.manager.pk)

        self.denied = mk_user('u@example.com', 'U')
        role_denied = mk_role(self.inst, can_manage_users=False)
        mk_instance_user(self.denied, self.inst, role_denied, is_active=True)
        self.denied = User.objects.get(pk=self.denied.pk)

        self.fp = Fingerprint.objects.create(instance=self.inst, value='fp-1', name='N1')

    def test_fingerprints_filter_by_values(self):
        Fingerprint.objects.create(instance=self.inst, value='fp-2', name='N2')
        api = APIClient()
        api.force_authenticate(user=self.manager)
        resp = api.get(f'/api/{self.inst.slug}/users/fingerprints/?values=fp-1')
        self.assertEqual(resp.status_code, 200)
        values = [row['value'] for row in _results(resp)]
        self.assertEqual(values, ['fp-1'])

    def test_fingerprint_update_requires_manage_users(self):
        api = APIClient()
        api.force_authenticate(user=self.denied)
        resp = api.patch(
            f'/api/{self.inst.slug}/users/fingerprints/{self.fp.id}/',
            data={'name': 'X'},
            format='json',
        )
        self.assertIn(resp.status_code, (400, 403))

        api = APIClient()
        api.force_authenticate(user=self.manager)
        resp = api.patch(
            f'/api/{self.inst.slug}/users/fingerprints/{self.fp.id}/',
            data={'name': 'X'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_fingerprint_delete_requires_manage_users(self):
        api = APIClient()
        api.force_authenticate(user=self.denied)
        resp = api.delete(f'/api/{self.inst.slug}/users/fingerprints/{self.fp.id}/')
        self.assertIn(resp.status_code, (400, 403))

        api = APIClient()
        api.force_authenticate(user=self.manager)
        resp = api.delete(f'/api/{self.inst.slug}/users/fingerprints/{self.fp.id}/')
        self.assertEqual(resp.status_code, 204)
