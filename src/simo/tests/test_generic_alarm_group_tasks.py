from unittest import mock

from django.utils import timezone

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class AlarmGroupTasksTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

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

    def test_notify_users_on_alarm_group_breach_sends_notification(self):
        from simo.generic.tasks import notify_users_on_alarm_group_breach

        with mock.patch('simo.notifications.utils.notify_users', autospec=True) as notify:
            notify_users_on_alarm_group_breach(self.alarm_group.id)

        notify.assert_called_once()
        args, kwargs = notify.call_args
        self.assertEqual(args[0], 'alarm')
        self.assertIn('Security Breach!', args[2])
        self.assertEqual(kwargs.get('component').id, self.alarm_group.id)
        self.assertEqual(kwargs.get('instance').id, self.inst.id)

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

