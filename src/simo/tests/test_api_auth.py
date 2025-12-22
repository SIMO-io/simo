from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory
from rest_framework import exceptions

from simo.core.api_auth import SecretKeyAuth, IsAuthenticated

from .base import BaseSimoTestCase, mk_instance, mk_role, mk_user, mk_instance_user


class ApiAuthTests(BaseSimoTestCase):
    def test_secret_key_auth_accepts_valid_secret(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)
        user.secret_key = 'secret'
        user.save(update_fields=['secret_key'])

        factory = APIRequestFactory()
        django_req = factory.get('/x', HTTP_SECRET='secret')

        auth = SecretKeyAuth()
        with mock.patch('simo.core.api_auth.introduce_user', autospec=True) as intro:
            res = auth.authenticate(django_req)

        self.assertIsNotNone(res)
        self.assertEqual(res[0].id, user.id)
        intro.assert_called_once()

    def test_is_authenticated_enforces_csrf_only_for_browsers(self):
        user = mk_user('u@example.com', 'U')
        factory = APIRequestFactory()

        auth = IsAuthenticated()

        # SIMO app UA => no CSRF
        req1 = factory.get('/x', HTTP_USER_AGENT='SIMO/1.0')
        req1.user = user
        drf_req1 = SimpleNamespace(_request=req1, META=req1.META)
        with mock.patch.object(auth, 'enforce_csrf', autospec=True) as enforce, \
                mock.patch('simo.core.api_auth.introduce_user', autospec=True):
            res = auth.authenticate(drf_req1)
        self.assertEqual(res[0].id, user.id)
        enforce.assert_not_called()

        # Browser UA => CSRF enforced
        req2 = factory.get('/x', HTTP_USER_AGENT='Mozilla/5.0')
        req2.user = user
        drf_req2 = SimpleNamespace(_request=req2, META=req2.META)
        with mock.patch.object(auth, 'enforce_csrf', autospec=True) as enforce, \
                mock.patch('simo.core.api_auth.introduce_user', autospec=True):
            res = auth.authenticate(drf_req2)
        self.assertEqual(res[0].id, user.id)
        enforce.assert_called_once()

    def test_is_authenticated_rejects_anonymous(self):
        factory = APIRequestFactory()
        req = factory.get('/x')
        req.user = AnonymousUser()
        drf_req = SimpleNamespace(_request=req, META=req.META)

        auth = IsAuthenticated()
        with self.assertRaises(exceptions.NotAuthenticated):
            auth.authenticate(drf_req)
