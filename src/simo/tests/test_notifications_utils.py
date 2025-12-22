from unittest import mock

from simo.core.middleware import get_current_instance, introduce_instance
from simo.core.models import Component, Gateway, Zone
from simo.notifications.models import Notification, UserNotification

from .base import BaseSimoTestCase, mk_instance, mk_role, mk_user, mk_instance_user


class NotifyUsersTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        self.comp = Component.objects.create(
            name='C',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

    def test_noop_when_no_instance_context_and_no_component(self):
        from simo.notifications.utils import notify_users

        self.assertIsNone(get_current_instance())
        notify_users('info', 'T', body='B', component=None, instance=None)
        self.assertEqual(Notification.objects.count(), 0)

    def test_filters_recipients_and_restores_current_instance(self):
        from simo.notifications.utils import notify_users

        # Start with an active instance context and ensure it is restored.
        introduce_instance(self.inst)
        self.assertEqual(get_current_instance().id, self.inst.id)

        user_ok = mk_user('ok@example.com', 'OK')
        role_ok = mk_role(self.inst, is_superuser=True)
        iu_ok = mk_instance_user(user_ok, self.inst, role_ok, is_active=True)

        user_system = mk_user('sys@simo.io', 'SYS')
        role_sys = mk_role(self.inst, is_superuser=True)
        iu_system = mk_instance_user(user_system, self.inst, role_sys, is_active=True)

        user_denied = mk_user('no@example.com', 'NO')
        role_denied = mk_role(self.inst, is_superuser=False)
        iu_denied = mk_instance_user(user_denied, self.inst, role_denied, is_active=True)

        other_inst = mk_instance('inst-b', 'B')
        user_other = mk_user('other@example.com', 'OTHER')
        role_other = mk_role(other_inst, is_superuser=True)
        iu_other = mk_instance_user(user_other, other_inst, role_other, is_active=True)

        with mock.patch('simo.notifications.models.Notification.dispatch', autospec=True) as dispatch:
            notify_users(
                'info',
                'Hello',
                body='Body',
                component=self.comp,
                instance=self.inst,
                instance_users=[iu_ok, iu_system, iu_denied, iu_other],
            )

        # One notification created.
        self.assertEqual(Notification.objects.count(), 1)
        notif = Notification.objects.first()
        self.assertEqual(notif.instance_id, self.inst.id)
        self.assertEqual(notif.severity, 'info')
        self.assertEqual(notif.title, f'{self.inst.name}: Hello')
        dispatch.assert_called_once()

        # Only the allowed recipient gets a UserNotification.
        self.assertEqual(UserNotification.objects.count(), 1)
        un = UserNotification.objects.first()
        self.assertEqual(un.user_id, user_ok.id)

        # Instance context is restored.
        self.assertIsNotNone(get_current_instance())
        self.assertEqual(get_current_instance().id, self.inst.id)

