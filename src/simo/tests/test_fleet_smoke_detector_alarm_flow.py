from unittest import mock

from simo.core.models import Component, Gateway, Zone
from simo.notifications.models import Notification, UserNotification

from .base import (
    BaseSimoTestCase,
    mk_instance,
    mk_instance_user,
    mk_role,
    mk_user,
)


class SmokeDetectorAlarmFlowTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        self.fleet_gw, _ = Gateway.objects.get_or_create(
            type='simo.fleet.gateways.FleetGatewayHandler'
        )
        self.generic_gw, _ = Gateway.objects.get_or_create(
            type='simo.generic.gateways.GenericGatewayHandler'
        )

        user = mk_user('alarm@example.com', 'Alarm User')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(user, self.inst, role, is_active=True)

        from simo.fleet.controllers import SmokeDetector
        from simo.generic.controllers import AlarmGroup

        self.smoke = Component.objects.create(
            name='Smoke',
            zone=self.zone,
            category=None,
            gateway=self.fleet_gw,
            base_type='binary-sensor',
            controller_uid=SmokeDetector.uid,
            config={},
            meta={},
            value=False,
            alarm_category='fire',
            arm_status='armed',
        )
        self.alarm_group = Component.objects.create(
            name='Fire Group',
            zone=self.zone,
            category=None,
            gateway=self.generic_gw,
            base_type='alarm-group',
            controller_uid=AlarmGroup.uid,
            config={
                'components': [self.smoke.id],
                'stats': {
                    'disarmed': 0,
                    'pending-arm': 0,
                    'armed': 1,
                    'breached': 0,
                },
                'breach_events': [],
                'notify_on_breach': 0,
            },
            meta={'breach_times': [], 'events_triggered': []},
            value='armed',
            alarm_category='fire',
        )

    def _run_notification_tasks_inline(self):
        from simo.generic.tasks import notify_users_on_alarm_group_breach

        def _side_effect(*, args=None, countdown=None, **kwargs):
            notify_users_on_alarm_group_breach(*args)

        return mock.patch(
            'simo.generic.models.notify_users_on_alarm_group_breach.apply_async',
            autospec=True,
            side_effect=_side_effect,
        )

    def test_duplicate_active_packets_keep_detector_and_group_breached(self):
        with self._run_notification_tasks_inline():
            with self.captureOnCommitCallbacks(execute=True):
                self.smoke.controller._receive_from_device([True, True])

        self.smoke.refresh_from_db()
        self.alarm_group.refresh_from_db()
        self.assertEqual(self.smoke.arm_status, 'breached')
        self.assertEqual(self.alarm_group.value, 'breached')
        self.assertEqual(self.alarm_group.arm_status, 'breached')
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(UserNotification.objects.count(), 1)

        with self._run_notification_tasks_inline():
            with self.captureOnCommitCallbacks(execute=True):
                self.smoke.controller._receive_from_device([True, True])

        self.smoke.refresh_from_db()
        self.alarm_group.refresh_from_db()
        self.assertEqual(self.smoke.arm_status, 'breached')
        self.assertEqual(self.alarm_group.value, 'breached')
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(UserNotification.objects.count(), 1)

    def test_legacy_true_packet_does_not_rearm_breached_detector(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.smoke.controller._receive_from_device([True, True])
        self.smoke.refresh_from_db()
        self.assertEqual(self.smoke.arm_status, 'breached')

        with self.captureOnCommitCallbacks(execute=True):
            self.smoke.controller._receive_from_device(True)

        self.smoke.refresh_from_db()
        self.assertEqual(self.smoke.arm_status, 'breached')

    def test_cleared_alarm_rearms_detector_without_pending_arm(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.smoke.controller._receive_from_device([True, True])
        self.smoke.refresh_from_db()
        self.assertEqual(self.smoke.arm_status, 'breached')

        with self.captureOnCommitCallbacks(execute=True):
            self.smoke.controller._receive_from_device([False, True])

        self.smoke.refresh_from_db()
        self.alarm_group.refresh_from_db()
        self.assertEqual(self.smoke.value, False)
        self.assertEqual(self.smoke.arm_status, 'armed')
        self.assertEqual(self.alarm_group.value, 'breached')

    def test_breach_notifications_schedule_post_commit_and_only_once_per_transition(self):
        with mock.patch('simo.notifications.utils.dispatch_notification_now', autospec=True) as dispatch:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.smoke.controller._receive_from_device([True, True])
                self.assertEqual(Notification.objects.count(), 1)
                self.assertEqual(UserNotification.objects.count(), 1)
                notification = Notification.objects.first()
                self.assertFalse(notification.is_pending)
                dispatch.assert_not_called()

            self.assertGreaterEqual(len(callbacks), 1)
            for callback in callbacks:
                callback()

        dispatch.assert_called_once_with(notification.id)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(UserNotification.objects.count(), 1)

    def test_delayed_breach_notification_rows_persist_and_cancel_when_group_disarms(self):
        from simo.generic.tasks import notify_users_on_alarm_group_breach

        self.alarm_group.config['notify_on_breach'] = 5
        self.alarm_group.save(update_fields=['config'])

        with mock.patch(
            'simo.generic.models.notify_users_on_alarm_group_breach.apply_async',
            autospec=True,
        ) as apply_async:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.smoke.controller._receive_from_device([True, True])
                notification = Notification.objects.first()
                self.assertIsNotNone(notification)
                self.assertTrue(notification.is_pending)
                self.assertEqual(UserNotification.objects.count(), 1)

            for callback in callbacks:
                callback()

        apply_async.assert_called_once()
        task_args = apply_async.call_args.kwargs['args']

        self.alarm_group.value = 'disarmed'
        self.alarm_group.save(update_fields=['value'])

        with mock.patch('simo.notifications.utils.dispatch_notification_now', autospec=True) as dispatch:
            notify_users_on_alarm_group_breach(*task_args)

        dispatch.assert_not_called()
        notification.refresh_from_db()
        self.assertFalse(notification.is_pending)
        self.assertIsNotNone(notification.cancelled)
        user_notification = UserNotification.objects.get(notification=notification)
        self.assertIsNone(user_notification.sent)
