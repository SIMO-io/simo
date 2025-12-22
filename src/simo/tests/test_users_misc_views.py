from django.test import Client

from simo.users.models import User

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class MqttCredentialsViewTests(BaseSimoTestCase):
    def test_mqtt_credentials_requires_login(self):
        client = Client()
        resp = client.get('/users/mqtt-credentials/')
        self.assertEqual(resp.status_code, 302)

    def test_mqtt_credentials_returns_expected_payload(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)
        user = User.objects.get(pk=user.pk)

        client = Client()
        client.force_login(user)
        resp = client.get('/users/mqtt-credentials/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['username'], user.email)
        self.assertEqual(data['password'], user.secret_key)
        self.assertEqual(data['user_id'], user.id)

