from unittest import mock

from django.test import Client

from simo.users.models import User

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class ProtectedMediaTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.other_inst = mk_instance('inst-b', 'B')

        self.user_a = mk_user('a@example.com', 'A')
        role_a = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.user_a, self.inst, role_a, is_active=True)
        self.user_a = User.objects.get(pk=self.user_a.pk)

        self.user_b = mk_user('b@example.com', 'B')
        role_b = mk_role(self.inst, is_superuser=False)
        mk_instance_user(self.user_b, self.inst, role_b, is_active=True)
        self.user_b = User.objects.get(pk=self.user_b.pk)

        self.user_c = mk_user('c@example.com', 'C')
        role_c = mk_role(self.other_inst, is_superuser=False)
        mk_instance_user(self.user_c, self.other_inst, role_c, is_active=True)
        self.user_c = User.objects.get(pk=self.user_c.pk)

    def test_static_is_available_for_authenticated_users(self):
        client = Client()
        client.force_login(self.user_a)
        resp = client.get('/static/admin/css/base.css')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('X-Accel-Redirect', resp.headers)

    def test_media_icons_is_allowed(self):
        client = Client()
        client.force_login(self.user_a)
        resp = client.get('/media/icons/anything.svg')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('X-Accel-Redirect', resp.headers)

    def test_media_instances_requires_membership(self):
        client = Client()
        client.force_login(self.user_a)
        resp = client.get(f'/media/instances/{self.inst.uid}/categories/x.jpg')
        self.assertEqual(resp.status_code, 200)

        client = Client()
        client.force_login(self.user_c)
        resp = client.get(f'/media/instances/{self.inst.uid}/categories/x.jpg')
        self.assertEqual(resp.status_code, 404)

    def test_media_allows_secret_key_auth(self):
        # No login, but valid secret header.
        client = Client()
        resp = client.get(
            f'/media/instances/{self.inst.uid}/categories/x.jpg',
            HTTP_SECRET=self.user_a.secret_key,
        )
        self.assertEqual(resp.status_code, 200)

    def test_media_avatars_requires_shared_instance(self):
        client = Client()
        client.force_login(self.user_a)
        resp = client.get(f'/media/avatars/{self.user_b.media_uid}/b.jpg')
        self.assertEqual(resp.status_code, 200)

        client = Client()
        client.force_login(self.user_c)
        resp = client.get(f'/media/avatars/{self.user_b.media_uid}/b.jpg')
        self.assertEqual(resp.status_code, 404)

    def test_media_path_traversal_is_denied(self):
        client = Client()
        client.force_login(self.user_a)
        resp = client.get('/media/../secrets.txt')
        self.assertEqual(resp.status_code, 404)

    def test_media_throttle_denies_access(self):
        client = Client()
        client.force_login(self.user_a)
        with mock.patch('simo.core.throttling.check_throttle', autospec=True, return_value=10):
            resp = client.get('/media/icons/anything.svg')
        self.assertEqual(resp.status_code, 404)
