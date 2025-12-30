from rest_framework.test import APIClient

from simo.notifications.models import Notification, UserNotification

from .base import BaseSimoTestCase, mk_instance, mk_role, mk_user, mk_instance_user


class SdkNotificationsSendTests(BaseSimoTestCase):
    def test_notifications_send_endpoint_creates_notification(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        iu = mk_instance_user(user, inst, role, is_active=True)
        user.secret_key = 'secret'
        user.save(update_fields=['secret_key'])

        client = APIClient()
        resp = client.post(
            f'/api/{inst.slug}/notifications/send/',
            {
                'severity': 'warning',
                'title': 'Hello',
                'body': 'Test',
                'instance_user_ids': [iu.id],
            },
            format='json',
            HTTP_SECRET='secret',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'status': 'success'})

        self.assertEqual(Notification.objects.filter(instance=inst).count(), 1)
        self.assertEqual(UserNotification.objects.filter(user=user).count(), 1)

