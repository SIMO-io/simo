import datetime
from unittest import mock

import pytz
from django.core.exceptions import ValidationError
from django.utils import timezone

from simo.core.models import Component, Gateway, Zone
from simo.core.utils.config_values import ConfigException

from .base import BaseSimoTestCase, mk_instance


class AlarmClockControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.inst.timezone = 'UTC'
        self.inst.save(update_fields=['timezone'])
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.controllers import AlarmClock, SwitchGroup

        self.target = Component.objects.create(
            name='T',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        self.clock = Component.objects.create(
            name='AC',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='alarm-clock',
            controller_uid=AlarmClock.uid,
            config={},
            meta=[],
            value=AlarmClock.default_value,
        )

    def test_set_user_config_rejects_non_list(self):
        with self.assertRaises(ValidationError):
            self.clock.controller.set_user_config({'x': 1})

    def test_set_user_config_raises_config_exception_on_invalid_alarm(self):
        bad = [{'week_days': 'nope', 'time': '99:99', 'events': [{}]}]
        with self.assertRaises(ConfigException):
            self.clock.controller.set_user_config(bad)

    def test_set_user_config_assigns_missing_uids_and_saves_meta(self):
        data = [
            {
                'name': 'Wake',
                'week_days': [1],
                'time': '7:00',
                'events': [
                    {
                        'name': 'Turn on',
                        'offset': 0,
                        'component': self.target.id,
                        'play_action': 'turn_on',
                        'reverse_action': 'turn_off',
                        'enabled': True,
                    }
                ],
            }
        ]

        with (
            mock.patch('simo.generic.controllers.get_random_string', side_effect=['EVT001', 'ALARM01']),
            mock.patch('simo.generic.controllers.AlarmClock._check_alarm', autospec=True, return_value={'in_alarm': False, 'events': [], 'events_triggered': [], 'alarm_timestamp': None}),
        ):
            out = self.clock.controller.set_user_config(data)

        self.assertEqual(out[0]['uid'], 'ALARM01')
        self.assertEqual(out[0]['events'][0]['uid'], 'EVT001')

        self.clock.refresh_from_db()
        self.assertEqual(self.clock.meta[0]['uid'], 'ALARM01')
        self.assertEqual(self.clock.meta[0]['events'][0]['uid'], 'EVT001')

    def test_check_alarm_calculates_next_alarm_and_event_fire_timestamps(self):
        now = pytz.utc.localize(datetime.datetime(2024, 1, 1, 6, 0, 0))  # Monday
        alarm = {
            'uid': 'a1',
            'enabled': True,
            'name': 'A',
            'week_days': [1],
            'time': '7:00',
            'events': [
                {'uid': 'e1', 'offset': -10, 'component': self.target.id, 'play_action': 'turn_on', 'enabled': True},
                {'uid': 'e2', 'offset': 0, 'component': self.target.id, 'play_action': 'turn_on', 'enabled': True},
            ],
        }

        current_value = {'in_alarm': False, 'events': [], 'events_triggered': [], 'alarm_timestamp': None, 'ignore_alarms': {}}
        expected_alarm_ts = now.replace(hour=7, minute=0, second=0).timestamp()

        with mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=now):
            out = self.clock.controller._check_alarm([alarm], current_value)

        self.assertEqual(out['alarm_uid'], 'a1')
        self.assertAlmostEqual(out['alarm_timestamp'], expected_alarm_ts, delta=1)
        self.assertEqual([e['uid'] for e in out['events']], ['e1', 'e2'])
        self.assertLess(out['events'][0]['fire_timestamp'], out['events'][1]['fire_timestamp'])
