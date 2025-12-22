from django.utils import timezone
from rest_framework.test import APIClient

from simo.notifications.models import Notification, UserNotification
from simo.notifications.utils import notify_users
from simo.core.middleware import get_current_instance, introduce_instance, drop_current_instance

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


def _results(resp):
    data = resp.json()
    return data.get('results', data)


class NotificationsApiTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.user = mk_user('u@example.com', 'U')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.user, self.inst, role, is_active=True)
        from simo.users.models import User

        self.user = User.objects.get(pk=self.user.pk)
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

    def test_notifications_list_is_user_scoped(self):
        other = mk_user('o@example.com', 'O')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(other, self.inst, role, is_active=True)

        n1 = Notification.objects.create(instance=self.inst, severity='info', title='T1')
        n2 = Notification.objects.create(instance=self.inst, severity='info', title='T2')
        UserNotification.objects.create(user=self.user, notification=n1)
        UserNotification.objects.create(user=other, notification=n2)

        resp = self.api.get(f'/api/{self.inst.slug}/notifications/')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in _results(resp)]
        self.assertIn(n1.id, ids)
        self.assertNotIn(n2.id, ids)

    def test_notifications_archive_action_sets_timestamp(self):
        n1 = Notification.objects.create(instance=self.inst, severity='info', title='T1')
        un = UserNotification.objects.create(user=self.user, notification=n1)
        self.assertIsNone(un.archived)

        resp = self.api.post(f'/api/{self.inst.slug}/notifications/{n1.id}/archive/')
        self.assertEqual(resp.status_code, 200)
        un.refresh_from_db()
        self.assertIsNotNone(un.archived)

    def test_notifications_archived_filter(self):
        n1 = Notification.objects.create(instance=self.inst, severity='info', title='T1')
        n2 = Notification.objects.create(instance=self.inst, severity='info', title='T2')
        UserNotification.objects.create(user=self.user, notification=n1, archived=timezone.now())
        UserNotification.objects.create(user=self.user, notification=n2, archived=None)

        resp = self.api.get(f'/api/{self.inst.slug}/notifications/?archived=1')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in _results(resp)]
        self.assertEqual(ids, [n1.id])


class NotifyUsersUtilTests(BaseSimoTestCase):
    def test_notify_users_creates_user_notifications_and_restores_instance(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)

        drop_current_instance()
        self.assertIsNone(get_current_instance())
        introduce_instance(inst)
        self.assertEqual(get_current_instance(), inst)

        notify_users('info', 'Hello', body='World', instance=inst)
        self.assertEqual(Notification.objects.filter(instance=inst).count(), 1)
        self.assertEqual(UserNotification.objects.filter(user=user).count(), 1)

        # verify instance context restored
        self.assertEqual(get_current_instance(), inst)

