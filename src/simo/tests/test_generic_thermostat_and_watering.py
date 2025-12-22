import datetime
from unittest import mock

import pytz
from django.core.exceptions import ValidationError
from django.utils import timezone

from simo.core.controllers import BEFORE_SEND
from simo.core.models import Component, Gateway, Zone
from simo.core.middleware import introduce_instance

from .base import BaseSimoTestCase, mk_instance


class ThermostatControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.controllers import Thermostat

        self.comp = Component.objects.create(
            name='T',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='thermostat',
            controller_uid=Thermostat.uid,
            config={
                'temperature_sensor': 0,
                'heaters': [],
                'coolers': [],
                'engagement': 'dynamic',
                'min': 4,
                'max': 36,
                'has_real_feel': False,
                'user_config': {},
            },
            meta={},
            value={'current_temp': 21, 'target_temp': 22, 'heating': False, 'cooling': False},
        )

    def test_default_config_uses_instance_units(self):
        from simo.generic.controllers import Thermostat

        self.inst.units_of_measure = 'metric'
        self.inst.save(update_fields=['units_of_measure'])
        introduce_instance(self.inst)
        cfg_metric = Thermostat(self.comp).default_config
        self.assertEqual(cfg_metric['min'], 4)
        self.assertEqual(cfg_metric['max'], 36)

        self.inst.units_of_measure = 'imperial'
        self.inst.save(update_fields=['units_of_measure'])
        introduce_instance(self.inst)
        cfg_imp = Thermostat(self.comp).default_config
        self.assertEqual(cfg_imp['min'], 40)
        self.assertEqual(cfg_imp['max'], 95)

    def test_get_target_from_custom_options_uses_localtime(self):
        options = {
            '24h': {'active': False, 'target': 21},
            'custom': [['07:00', 22], ['20:00', 17]],
        }

        dt_19 = pytz.utc.localize(datetime.datetime(2024, 1, 1, 19, 0, 0))
        dt_21 = pytz.utc.localize(datetime.datetime(2024, 1, 1, 21, 0, 0))

        with mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt_19):
            self.assertEqual(self.comp.controller._get_target_from_options(options), 22)
        with mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt_21):
            self.assertEqual(self.comp.controller._get_target_from_options(options), 17)

    def test_get_current_target_temperature_prefers_hard_hold(self):
        self.comp.config['user_config'] = {
            'hard': {'active': True, 'target': 99},
            'daily': {'active': True, 'options': {'24h': {'active': True, 'target': 21}, 'custom': []}},
            'weekly': {'1': {'24h': {'active': True, 'target': 22}, 'custom': []}},
        }
        self.comp.save(update_fields=['config'])
        self.comp.refresh_from_db()

        self.assertEqual(self.comp.controller.get_current_target_temperature(), 99)

    def test_engage_devices_switch_and_dimmer_routing(self):
        dimmer = mock.Mock(base_type='dimmer')
        switch = mock.Mock(base_type='switch')

        self.comp.controller._engage_devices([dimmer, switch], 100)
        dimmer.output_percent.assert_called_once_with(100)
        switch.turn_on.assert_called_once()

        dimmer.reset_mock()
        switch.reset_mock()
        self.comp.controller._engage_devices([dimmer, switch], 0)
        dimmer.output_percent.assert_called_once_with(0)
        switch.turn_off.assert_called_once()

        dimmer.reset_mock()
        switch.reset_mock()
        self.comp.controller._engage_devices([dimmer, switch], 55)
        dimmer.output_percent.assert_called_once_with(55)
        switch.pulse.assert_called_once_with(30, 55)


class WateringControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.controllers import Watering, SwitchGroup

        self.s1 = Component.objects.create(
            name='S1',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        self.s2 = Component.objects.create(
            name='S2',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        self.comp = Component.objects.create(
            name='W',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='watering',
            controller_uid=Watering.uid,
            config={
                'contours': [
                    {'uid': 'c1', 'switch': self.s1.id},
                    {'uid': 'c2', 'switch': self.s2.id},
                ],
                'program': {
                    'duration': 10,
                    'flow': [
                        {'minute': 0, 'contours': ['c1']},
                        {'minute': 5, 'contours': ['c2']},
                    ],
                },
                'schedule': {
                    'mode': 'off',
                    'daily': [],
                    'weekly': {str(i): [] for i in range(1, 8)},
                },
            },
            meta={},
            value={'status': 'stopped', 'program_progress': 0},
        )

    def test_validate_before_send_rejects_unknown_command(self):
        with self.assertRaises(ValidationError):
            self.comp.controller._validate_val('boom', occasion=BEFORE_SEND)

    def test_validate_before_set_rejects_bad_shapes(self):
        with self.assertRaises(ValidationError):
            self.comp.controller._validate_val('not-dict', occasion=None)

        with self.assertRaises(ValidationError):
            self.comp.controller._validate_val({'x': 1}, occasion=None)

        with self.assertRaises(ValidationError):
            self.comp.controller._validate_val({'program_progress': 999}, occasion=None)

    def test_set_program_progress_engages_expected_contours(self):
        with (
            mock.patch('simo.core.controllers.Switch.turn_on', autospec=True) as turn_on,
            mock.patch('simo.core.controllers.Switch.turn_off', autospec=True) as turn_off,
        ):
            self.comp.controller._set_program_progress(0, run=True)

        self.assertEqual([c.args[0].component.id for c in turn_on.call_args_list], [self.s1.id])
        self.assertEqual([c.args[0].component.id for c in turn_off.call_args_list], [self.s2.id])

        with (
            mock.patch('simo.core.controllers.Switch.turn_on', autospec=True) as turn_on,
            mock.patch('simo.core.controllers.Switch.turn_off', autospec=True) as turn_off,
        ):
            self.comp.controller._set_program_progress(6, run=True)

        self.assertEqual([c.args[0].component.id for c in turn_on.call_args_list], [self.s2.id])
        self.assertEqual([c.args[0].component.id for c in turn_off.call_args_list], [self.s1.id])

    def test_set_program_progress_past_duration_stops_program(self):
        with (
            mock.patch('simo.core.controllers.Switch.turn_on', autospec=True),
            mock.patch('simo.core.controllers.Switch.turn_off', autospec=True),
        ):
            self.comp.controller._set_program_progress(99, run=True)

        self.comp.refresh_from_db()
        self.assertEqual(self.comp.value, {'status': 'stopped', 'program_progress': 0})

    def test_get_next_run_daily_and_weekly(self):
        # Daily: pick next time today.
        self.comp.config['schedule'] = {
            'mode': 'daily',
            'daily': ['11:00', '12:00'],
            'weekly': {str(i): [] for i in range(1, 8)},
        }
        self.comp.save(update_fields=['config'])

        dt = pytz.utc.localize(datetime.datetime(2024, 1, 1, 10, 15, 30))
        expected = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 11 * 3600
        with mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt):
            out = self.comp.controller._get_next_run()
        self.assertAlmostEqual(out, expected, delta=1)

        # Weekly: next day schedule.
        self.comp.refresh_from_db()
        self.comp.config['schedule'] = {
            'mode': 'weekly',
            'daily': [],
            'weekly': {str(i): [] for i in range(1, 8)},
        }
        self.comp.config['schedule']['weekly']['2'] = ['08:00']
        self.comp.save(update_fields=['config'])

        dt = pytz.utc.localize(datetime.datetime(2024, 1, 1, 9, 0, 0))  # Monday
        expected = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 24 * 3600 + 8 * 3600
        with mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt):
            out = self.comp.controller._get_next_run()
        self.assertAlmostEqual(out, expected, delta=1)

    def test_perform_schedule_triggers_start_within_gap(self):
        from simo.generic.controllers import Watering

        self.comp.config['schedule'] = {
            'mode': 'daily',
            'daily': ['10:00'],
            'weekly': {str(i): [] for i in range(1, 8)},
        }
        self.comp.value = {'status': 'stopped', 'program_progress': 0}
        self.comp.save(update_fields=['config', 'value'])

        dt = timezone.make_aware(datetime.datetime(2024, 1, 1, 10, 10, 0), pytz.utc)

        with (
            mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt),
            mock.patch.object(Watering, 'reset', autospec=True) as reset,
            mock.patch.object(Watering, 'start', autospec=True) as start,
        ):
            self.comp.controller._perform_schedule()

        reset.assert_called_once()
        start.assert_called_once()

