import tempfile
import time
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from simo.core.middleware import get_current_instance
from simo.core.models import Instance, Zone, Category, Gateway, Component
from simo.users.models import User, PermissionsRole, InstanceUser


def _mk_instance(uid: str, name: str):
    return Instance.objects.create(uid=uid, name=name, slug=uid)


def _mk_user(email: str, name: str, *, is_master=False):
    return User.objects.create(email=email, name=name, is_master=is_master)


def _mk_role(instance: Instance, *, is_superuser=False, is_owner=False, can_manage_users=False):
    return PermissionsRole.objects.create(
        instance=instance,
        name='role',
        is_superuser=is_superuser,
        is_owner=is_owner,
        can_manage_users=can_manage_users,
    )


class BaseSimoTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._patches = [
            mock.patch('simo.users.models.User.update_mqtt_secret', autospec=True),
            mock.patch('simo.users.utils.update_mqtt_acls', autospec=True),
            mock.patch('simo.users.utils.rebuild_authorized_keys', autospec=True),
            mock.patch('simo.core.events.GatewayObjectCommand.publish', autospec=True),
        ]
        for p in cls._patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, '_patches', []):
            try:
                p.stop()
            except Exception:
                pass
        super().tearDownClass()

    def setUp(self):
        from django.core.cache import cache
        from simo.core.middleware import drop_current_instance
        from simo.users.utils import introduce_user

        drop_current_instance()
        introduce_user(None)
        try:
            cache.clear()
        except Exception:
            pass

    def tearDown(self):
        from simo.core.middleware import drop_current_instance
        from simo.users.utils import introduce_user

        drop_current_instance()
        introduce_user(None)
        super().tearDown()


class MultiTenantIsolationTests(BaseSimoTestCase):
    def test_instance_context_resets_between_requests(self):
        inst_a = _mk_instance('inst-a', 'A')
        inst_b = _mk_instance('inst-b', 'B')

        client = APIClient()
        resp = client.get(f'/api/{inst_a.slug}/core/info/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(get_current_instance())

        resp = client.get(f'/api/{inst_b.slug}/core/info/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(get_current_instance())

    def test_user_cannot_access_other_instance_api(self):
        inst_a = _mk_instance('inst-a', 'A')
        inst_b = _mk_instance('inst-b', 'B')

        user_a = _mk_user('a@example.com', 'A')
        role_a = _mk_role(inst_a, is_superuser=True)
        InstanceUser.objects.create(user=user_a, instance=inst_a, role=role_a, is_active=True)
        user_a = User.objects.get(pk=user_a.pk)

        client = APIClient()
        client.force_authenticate(user=user_a)

        # Allowed
        resp = client.get(f'/api/{inst_a.slug}/core/settings/')
        self.assertEqual(resp.status_code, 200)

        # Denied
        resp = client.get(f'/api/{inst_b.slug}/core/settings/')
        self.assertIn(resp.status_code, (403, 404))


class MediaIsolationTests(BaseSimoTestCase):
    def test_instance_scoped_media_isolated(self):
        inst_a = _mk_instance('inst-a', 'A')
        inst_b = _mk_instance('inst-b', 'B')

        user_a = _mk_user('a@example.com', 'A')
        role_a = _mk_role(inst_a, is_superuser=True)
        InstanceUser.objects.create(user=user_a, instance=inst_a, role=role_a, is_active=True)

        role_b = _mk_role(inst_b, is_superuser=True)
        user_b = _mk_user('b@example.com', 'B')
        InstanceUser.objects.create(user=user_b, instance=inst_b, role=role_b, is_active=True)

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                cat_b = Category.objects.create(instance=inst_b, name='C', icon_id=None, order=0)
                cat_b.header_image = SimpleUploadedFile('hb.jpg', b'123', content_type='image/jpeg')
                cat_b.save()

                client = Client()
                client.force_login(user_a)

                # Own instance media not present -> 404 ok
                resp = client.get('/media/instances/%s/categories/hb.jpg' % inst_a.uid)
                self.assertIn(resp.status_code, (200, 404))

                # Other instance must be denied
                resp = client.get('/media/%s' % cat_b.header_image.name)
                self.assertEqual(resp.status_code, 404)

    def test_avatar_media_requires_shared_instance(self):
        inst_a = _mk_instance('inst-a', 'A')
        inst_b = _mk_instance('inst-b', 'B')

        user_a = _mk_user('a@example.com', 'A')
        role_a = _mk_role(inst_a, is_superuser=True)
        InstanceUser.objects.create(user=user_a, instance=inst_a, role=role_a, is_active=True)

        user_b = _mk_user('b@example.com', 'B')
        role_b = _mk_role(inst_b, is_superuser=True)
        InstanceUser.objects.create(user=user_b, instance=inst_b, role=role_b, is_active=True)

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                user_b.avatar = SimpleUploadedFile('b.jpg', b'123', content_type='image/jpeg')
                user_b.save()

                client = Client()
                client.force_login(user_a)

                resp = client.get('/media/%s' % user_b.avatar.name)
                self.assertEqual(resp.status_code, 404)


class ControlSurfaceTests(BaseSimoTestCase):
    def test_masters_only_controller_denies_non_master_even_if_superuser(self):
        inst = _mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)

        # Create a gateway row for the automations gateway (type uid comes from handler)
        # We don't need it to actually run in tests.
        from simo.automation.gateways import AutomationsGatewayHandler
        gw, _ = Gateway.objects.get_or_create(type=AutomationsGatewayHandler.uid)

        from simo.automation.controllers import Script
        script = Component.objects.create(
            name='S',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='script',
            controller_uid=Script.uid,
            config={},
            meta={},
        )

        non_master = _mk_user('u@example.com', 'U')
        role = _mk_role(inst, is_superuser=True)
        InstanceUser.objects.create(user=non_master, instance=inst, role=role, is_active=True)
        non_master = User.objects.get(pk=non_master.pk)

        client = APIClient()
        client.force_authenticate(user=non_master)
        resp = client.post(
            f'/api/{inst.slug}/core/components/{script.id}/controller/',
            data={'start': []},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_disallowed_method_is_rejected(self):
        inst = _mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        user = _mk_user('u@example.com', 'U')
        role = _mk_role(inst, is_superuser=True)
        InstanceUser.objects.create(user=user, instance=inst, role=role, is_active=True)

        # Use a simple generic controller
        from simo.generic.controllers import SwitchGroup
        from simo.generic.gateways import GenericGatewayHandler

        gw, _ = Gateway.objects.get_or_create(type=GenericGatewayHandler.uid)
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

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            f'/api/{inst.slug}/core/components/{comp.id}/controller/',
            data={'delete': []},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)


class ThrottleInvariantsTests(BaseSimoTestCase):
    def test_ban_expires(self):
        from simo.core.throttling import check_throttle, SimpleRequest

        inst = _mk_instance('inst-a', 'A')
        user = _mk_user('u@example.com', 'U')
        role = _mk_role(inst, is_superuser=True)
        InstanceUser.objects.create(user=user, instance=inst, role=role, is_active=True)

        with override_settings(
            SIMO_THROTTLE={
                'ban_seconds': 1,
                'global_rules': [{'window_seconds': 1, 'limit_authenticated': 1, 'limit_anonymous': 1}],
                'default_rules': [{'window_seconds': 1, 'limit_authenticated': 1, 'limit_anonymous': 1}],
                'scopes': {},
            }
        ):
            req = SimpleRequest(user=user)
            self.assertEqual(check_throttle(request=req, scope='x'), 0)
            wait = check_throttle(request=req, scope='x')
            self.assertGreater(wait, 0)
            time.sleep(1.2)
            self.assertEqual(check_throttle(request=req, scope='x'), 0)

    def test_fail_open_on_cache_errors(self):
        from simo.core.throttling import check_throttle, SimpleRequest

        user = _mk_user('u@example.com', 'U')
        req = SimpleRequest(user=user)

        with mock.patch('django.core.cache.cache.incr', side_effect=Exception('down')):
            self.assertEqual(check_throttle(request=req, scope='x'), 0)
