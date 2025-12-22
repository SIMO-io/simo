import asyncio
import datetime
from unittest import mock

from django.utils import timezone
from django.test import TransactionTestCase

from simo.mcp_server.auth import DjangoTokenVerifier
from simo.mcp_server.models import InstanceAccessToken
from simo.mcp_server.tasks import auto_expire_tokens

from .base import BaseSimoTestCase, mk_instance


class McpServerAuthTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        from simo.core.middleware import drop_current_instance

        drop_current_instance()
        self.inst = mk_instance('inst-a', 'A')

    def test_verify_token_returns_access_token(self):
        InstanceAccessToken.objects.create(instance=self.inst, token='abc', issuer='test')
        verifier = DjangoTokenVerifier()

        with mock.patch('simo.mcp_server.auth.introduce_instance', autospec=True) as intro:
            res = asyncio.run(verifier.verify_token('abc'))

        self.assertIsNotNone(res)
        self.assertEqual(res.token, 'abc')
        intro.assert_called_once()

    def test_verify_token_returns_none_for_unknown(self):
        verifier = DjangoTokenVerifier()
        res = asyncio.run(verifier.verify_token('missing'))
        self.assertIsNone(res)


class McpServerTasksTests(BaseSimoTestCase):
    def test_auto_expire_tokens_marks_old_tokens(self):
        inst = mk_instance('inst-a', 'A')
        token = InstanceAccessToken.objects.create(instance=inst, token='old', issuer='test')
        InstanceAccessToken.objects.filter(id=token.id).update(
            date_created=timezone.now() - datetime.timedelta(days=2),
            date_expired=None,
        )

        auto_expire_tokens()

        token.refresh_from_db()
        self.assertIsNotNone(token.date_expired)


class McpServerTokenUniquenessTests(BaseSimoTestCase):
    def test_get_new_token_retries_on_collision(self):
        from simo.core.middleware import introduce_instance
        from simo.mcp_server import models

        inst = mk_instance('inst-a', 'A')
        introduce_instance(inst)

        InstanceAccessToken.objects.create(instance=inst, token='dup', issuer='test')

        with mock.patch('simo.mcp_server.models.get_random_string', autospec=True, side_effect=['dup', 'uniq']):
            token = models.get_new_token()
        self.assertEqual(token, 'uniq')
