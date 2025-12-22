from unittest import mock

from django.test import Client

from .base import BaseSimoTestCase


class SSOViewsTests(BaseSimoTestCase):

    def test_login_view_returns_json_for_simo_app(self):
        client = Client()

        fake_consumer = mock.Mock()
        fake_consumer.consume.return_value = {'request_token': 'rt'}

        with mock.patch('simo.users.sso_views.SyncConsumer', autospec=True, return_value=fake_consumer), \
                mock.patch('simo.users.sso_views.dynamic_settings', {'core__hub_secret': 'hs', 'core__hub_uid': 'hu'}):
            resp = client.get('/login/', HTTP_USER_AGENT='SIMO/1.0')

        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'redirect'
        assert 'url' in data

    def test_login_view_next_denies_external_host(self):
        client = Client()
        fake_consumer = mock.Mock()
        fake_consumer.consume.return_value = {'request_token': 'rt'}

        with mock.patch('simo.users.sso_views.SyncConsumer', autospec=True, return_value=fake_consumer), \
                mock.patch('simo.users.sso_views.dynamic_settings', {'core__hub_secret': 'hs', 'core__hub_uid': 'hu'}):
            resp = client.get('/login/?next=https://evil.example.com/', HTTP_USER_AGENT='SIMO/1.0')

        assert resp.status_code == 200

    def test_authenticate_view_returns_unauthorized_for_simo_app_when_auth_fails(self):
        client = Client()
        fake_consumer = mock.Mock()
        fake_consumer.consume.return_value = {'email': 'u@example.com', 'name': 'U'}

        with mock.patch('simo.users.sso_views.SyncConsumer', autospec=True, return_value=fake_consumer), \
                mock.patch('itsdangerous.URLSafeTimedSerializer.loads', autospec=True, return_value='token'), \
                mock.patch('simo.users.sso_views.authenticate', autospec=True, return_value=None), \
                mock.patch('simo.users.sso_views.dynamic_settings', {'core__hub_secret': 'hs', 'core__hub_uid': 'hu'}):
            resp = client.get(
                '/login/authenticate/?access_token=x',
                HTTP_USER_AGENT='SIMO/1.0',
            )

        assert resp.status_code == 403
        assert resp.json()['status'] == 'unauthorized'
