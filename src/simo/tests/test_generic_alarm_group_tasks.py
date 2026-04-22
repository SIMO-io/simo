from unittest import mock

from django.utils import timezone

from simo.core.models import Component, Gateway, Zone
from simo.notifications.models import Notification, UserNotification

from .base import BaseSimoTestCase, mk_instance, mk_instance_user, mk_role, mk_user


class AlarmGroupTasksTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        user = mk_user('alarm@example.com', 'Alarm User')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(user, self.inst, role, is_active=True)

        from simo.generic.controllers import AlarmGroup, SwitchGroup

        self.breached_sensor = Component.objects.create(
            name='Door',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
            arm_status='breached',
        )
        self.event_target = Component.objects.create(
            name='Siren',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        self.alarm_group = Component.objects.create(
            name='AG',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='alarm-group',
            controller_uid=AlarmGroup.uid,
            config={
                'components': [self.breached_sensor.id],
                'stats': {'disarmed': 0, 'pending-arm': 0, 'armed': 0, 'breached': 0},
                'breach_events': [
                    {
                        'uid': 'e1',
                        'component': self.event_target.id,
                        'breach_action': 'turn_on',
                        'threshold': 2,
                        'delay': 5,
                    }
                ],
            },
            meta={'breach_times': [], 'events_triggered': []},
            value='breached',
        )

    def test_notify_users_on_alarm_group_breach_dispatches_persisted_notification(self):
        from simo.generic.tasks import notify_users_on_alarm_group_breach
        from simo.notifications.utils import create_notification

        self.alarm_group.meta['breach_transition_id'] = 'breach-1'
        self.alarm_group.save(update_fields=['meta'])
        notification = create_notification(
            'alarm',
            str(self.alarm_group),
            body='Security Breach! Door',
            component=self.alarm_group,
            instance=self.inst,
            dispatch=False,
            dispatch_countdown=5,
            event_key='breach-1',
        )

        with mock.patch('simo.notifications.utils.dispatch_notification_now', autospec=True) as dispatch:
            notify_users_on_alarm_group_breach(
                notification.id, self.alarm_group.id, 'breach-1'
            )

        dispatch.assert_called_once_with(notification.id)
        notification.refresh_from_db()
        self.assertFalse(notification.is_pending)
        self.assertIsNone(notification.cancelled)
        self.assertEqual(UserNotification.objects.filter(notification=notification).count(), 1)

    def test_notify_users_on_alarm_group_breach_cancels_pending_notification_when_group_clears(self):
        from simo.generic.tasks import notify_users_on_alarm_group_breach
        from simo.notifications.utils import create_notification

        self.alarm_group.meta['breach_transition_id'] = 'breach-1'
        self.alarm_group.save(update_fields=['meta'])
        notification = create_notification(
            'alarm',
            str(self.alarm_group),
            body='Security Breach! Door',
            component=self.alarm_group,
            instance=self.inst,
            dispatch=False,
            dispatch_countdown=5,
            event_key='breach-1',
        )
        self.alarm_group.value = 'disarmed'
        self.alarm_group.save(update_fields=['value'])

        with mock.patch('simo.notifications.utils.dispatch_notification_now', autospec=True) as dispatch:
            notify_users_on_alarm_group_breach(
                notification.id, self.alarm_group.id, 'breach-1'
            )

        dispatch.assert_not_called()
        notification.refresh_from_db()
        self.assertFalse(notification.is_pending)
        self.assertIsNotNone(notification.cancelled)

    def test_fire_breach_events_respects_threshold_delay_and_idempotency(self):
        from simo.generic.tasks import fire_breach_events

        self.alarm_group.meta['breach_times'] = [100, 120]
        self.alarm_group.meta['events_triggered'] = []
        self.alarm_group.save(update_fields=['meta'])

        # Not enough delay => no action.
        with (
            mock.patch('simo.generic.tasks.time.time', autospec=True, return_value=123),
            mock.patch('simo.core.controllers.Switch.turn_on', autospec=True) as turn_on,
        ):
            fire_breach_events(self.alarm_group.id)
        turn_on.assert_not_called()

        # Enough delay => triggers once and records uid.
        with (
            mock.patch('simo.generic.tasks.time.time', autospec=True, return_value=130),
            mock.patch('simo.core.controllers.Switch.turn_on', autospec=True) as turn_on,
        ):
            fire_breach_events(self.alarm_group.id)
        turn_on.assert_called_once()

        ag = Component.objects.get(pk=self.alarm_group.pk)
        self.assertIn('e1', ag.meta.get('events_triggered', []))

        # Subsequent runs must not re-trigger.
        with (
            mock.patch('simo.generic.tasks.time.time', autospec=True, return_value=999),
            mock.patch('simo.core.controllers.Switch.turn_on', autospec=True) as turn_on,
        ):
            fire_breach_events(self.alarm_group.id)
        turn_on.assert_not_called()
