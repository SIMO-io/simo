from rest_framework.test import APIClient

from .base import BaseSimoTestCase, mk_instance, mk_role, mk_user, mk_instance_user


class WhoAmITests(BaseSimoTestCase):
    def test_whoami_with_secret_key(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)
        user.secret_key = 'secret'
        user.save(update_fields=['secret_key'])

        client = APIClient()
        resp = client.get('/users/whoami/?instance=inst-a', HTTP_SECRET='secret')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['user']['id'], user.id)
        self.assertEqual(data['selected_instance']['uid'], inst.uid)


class InstanceUsersApiTests(BaseSimoTestCase):
    def test_instance_users_endpoint_returns_members(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)
        user.secret_key = 'secret'
        user.save(update_fields=['secret_key'])

        client = APIClient()
        resp = client.get(f'/api/{inst.slug}/users/instance-users/', HTTP_SECRET='secret')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['email'], user.email)

