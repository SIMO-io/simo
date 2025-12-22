from unittest import mock

from django.utils import timezone

from simo.notifications.models import Notification, UserNotification
from simo.users.models import UserDevice

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class NotificationDispatchTests(BaseSimoTestCase):
    def test_dispatch_marks_user_notifications_sent_on_success(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)

        device = UserDevice.objects.create(os='ios', token='t1', is_primary=True)
        device.users.add(user)

        n = Notification.objects.create(instance=inst, severity='info', title='T')
        un = UserNotification.objects.create(user=user, notification=n)

        import simo.notifications.models as notif_models

        resp = mock.Mock()
        resp.json.return_value = {'status': 'success'}

        notif_models.requests.post.reset_mock()
        notif_models.requests.post.return_value = resp

        with mock.patch('simo.notifications.models.dynamic_settings', {'core__hub_secret': 'hs'}):
            n.dispatch()

        notif_models.requests.post.assert_called_once()
        un.refresh_from_db()
        self.assertIsNotNone(un.sent)

    def test_dispatch_does_not_mark_sent_on_failure(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)

        n = Notification.objects.create(instance=inst, severity='info', title='T')
        un = UserNotification.objects.create(user=user, notification=n)

        import simo.notifications.models as notif_models

        resp = mock.Mock()
        resp.json.return_value = {'status': 'error'}

        notif_models.requests.post.reset_mock()
        notif_models.requests.post.return_value = resp

        with mock.patch('simo.notifications.models.dynamic_settings', {'core__hub_secret': 'hs'}):
            n.dispatch()

        un.refresh_from_db()
        self.assertIsNone(un.sent)
