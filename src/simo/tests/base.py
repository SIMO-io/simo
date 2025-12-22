import contextlib
from unittest import mock

from django.test import TestCase, TransactionTestCase


def mk_instance(uid: str, name: str):
    from simo.core.models import Instance
    from django.db.models.signals import post_save
    from simo.core.signal_receivers import create_instance_defaults

    # Avoid noisy side effects during unit tests (default zones/categories,
    # copying media, creating default components).
    post_save.disconnect(create_instance_defaults, sender=Instance)
    try:
        return Instance.objects.create(uid=uid, name=name, slug=uid)
    finally:
        post_save.connect(create_instance_defaults, sender=Instance)


def mk_user(email: str, name: str, *, is_master: bool = False):
    from simo.users.models import User

    return User.objects.create(email=email, name=name, is_master=is_master)


def mk_role(
    instance,
    *,
    is_superuser: bool = False,
    is_owner: bool = False,
    can_manage_users: bool = False,
    is_default: bool = False,
):
    from simo.users.models import PermissionsRole

    return PermissionsRole.objects.create(
        instance=instance,
        name='role',
        is_superuser=is_superuser,
        is_owner=is_owner,
        can_manage_users=can_manage_users,
        is_default=is_default,
    )


def mk_instance_user(user, instance, role, *, is_active: bool = True):
    from simo.users.models import InstanceUser

    return InstanceUser.objects.create(
        user=user,
        instance=instance,
        role=role,
        is_active=is_active,
    )


@contextlib.contextmanager
def cleared_cache():
    from django.core.cache import cache

    try:
        cache.clear()
    except Exception:
        pass
    yield
    try:
        cache.clear()
    except Exception:
        pass


class BaseSimoTestCase(TestCase):
    """Base class that blocks external side effects.

    We keep tests black-box and avoid touching production code.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._dummy_mqtt_hub = mock.Mock()
        cls._patches = [
            mock.patch('simo.users.models.User.update_mqtt_secret', autospec=True),
            mock.patch('simo.users.utils.update_mqtt_acls', autospec=True),
            mock.patch('simo.users.utils.rebuild_authorized_keys', autospec=True),
            mock.patch('simo.users.models.rebuild_authorized_keys', autospec=True),
            mock.patch('simo.core.events.GatewayObjectCommand.publish', autospec=True),
            mock.patch('simo.core.models.Gateway.start', autospec=True),
            mock.patch('simo.notifications.models.requests.post', autospec=True),
            mock.patch('simo.core.mqtt_hub.get_mqtt_hub', autospec=True, return_value=cls._dummy_mqtt_hub),
        ]
        for patcher in cls._patches:
            patcher.start()

    @classmethod
    def tearDownClass(cls):
        for patcher in getattr(cls, '_patches', []):
            try:
                patcher.stop()
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


class BaseSimoTransactionTestCase(TransactionTestCase):
    """TransactionTestCase variant for async/channels tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._dummy_mqtt_hub = mock.Mock()
        cls._patches = [
            mock.patch('simo.users.models.User.update_mqtt_secret', autospec=True),
            mock.patch('simo.users.utils.update_mqtt_acls', autospec=True),
            mock.patch('simo.users.utils.rebuild_authorized_keys', autospec=True),
            mock.patch('simo.users.models.rebuild_authorized_keys', autospec=True),
            mock.patch('simo.core.events.GatewayObjectCommand.publish', autospec=True),
            mock.patch('simo.core.models.Gateway.start', autospec=True),
            mock.patch('simo.notifications.models.requests.post', autospec=True),
            mock.patch('simo.core.mqtt_hub.get_mqtt_hub', autospec=True, return_value=cls._dummy_mqtt_hub),
        ]
        for patcher in cls._patches:
            patcher.start()

    @classmethod
    def tearDownClass(cls):
        for patcher in getattr(cls, '_patches', []):
            try:
                patcher.stop()
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
