import datetime
from unittest import mock

import pytz
from django.core.exceptions import ValidationError
from django.utils import timezone

from simo.core.controllers import BEFORE_SEND
from simo.core.models import Component, ComponentHistory, Gateway, Zone
from simo.core.middleware import introduce_instance
from simo.users.utils import get_system_user

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
        switch = mock.Mock(base_type='switch', meta={}, value=False)

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
        switch.pulse.assert_called_once_with(300, 55)

    def test_engage_devices_switch_clamps_short_on_phase_to_off(self):
        switch = mock.Mock(
            base_type='switch',
            meta={'pulse': {'frame': 300, 'duty': 0.5}},
            value=True,
        )

        self.comp.controller._engage_devices([switch], 3)

        switch.turn_off.assert_called_once()
        switch.pulse.assert_not_called()

    def test_engage_devices_switch_clamps_short_off_phase_to_on(self):
        switch = mock.Mock(base_type='switch', meta={}, value=False)

        self.comp.controller._engage_devices([switch], 97)

        switch.turn_on.assert_called_once()
        switch.pulse.assert_not_called()

    def test_engage_devices_switch_does_not_restart_same_pulse(self):
        switch = mock.Mock(
            base_type='switch',
            meta={'pulse': {'frame': 300, 'duty': 0.55}},
            value=True,
        )

        self.comp.controller._engage_devices([switch], 55)

        switch.turn_on.assert_not_called()
        switch.turn_off.assert_not_called()
        switch.pulse.assert_not_called()


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
                    {'uid': 'c1', 'switch': self.s1.id, 'runtime': 5, 'occupation': 100},
                    {'uid': 'c2', 'switch': self.s2.id, 'runtime': 6, 'occupation': 100},
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

    def _weather_payload(
        self, dt_ts, *, temp=15.0, humidity=70, wind=3.0, rain_1h=0.0
    ):
        payload = {
            'dt': int(dt_ts),
            'main': {
                'temp': temp,
                'humidity': humidity,
                'pressure': 1000,
                'feels_like': temp,
            },
            'wind': {'speed': wind},
            'clouds': {'all': 60},
            'sys': {
                'sunrise': int(dt_ts - 6 * 3600),
                'sunset': int(dt_ts + 6 * 3600),
            },
            'weather': [{'main': 'Clouds', 'description': 'broken clouds'}],
        }
        if rain_1h:
            payload['rain'] = {'1h': rain_1h}
            payload['weather'] = [{'main': 'Rain', 'description': 'light rain'}]
        return payload

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

    def test_update_estimated_moisture_uses_weather_history(self):
        from simo.generic.controllers import Weather

        now_dt = timezone.make_aware(datetime.datetime(2024, 1, 1, 10, 10, 0), pytz.utc)
        weather = Component.objects.create(
            name='Weather',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='weather',
            controller_uid=Weather.uid,
            config={'is_main': True},
            meta={},
            value=self._weather_payload(now_dt.timestamp(), rain_1h=1.2),
        )
        old_item = ComponentHistory.objects.create(
            component=weather,
            type='value',
            value=self._weather_payload((now_dt - datetime.timedelta(minutes=20)).timestamp(), rain_1h=0.8),
            user=get_system_user(),
        )
        ComponentHistory.objects.filter(id=old_item.id).update(
            date=now_dt - datetime.timedelta(minutes=20)
        )
        new_item = ComponentHistory.objects.create(
            component=weather,
            type='value',
            value=self._weather_payload((now_dt - datetime.timedelta(minutes=10)).timestamp(), rain_1h=1.2),
            user=get_system_user(),
        )
        ComponentHistory.objects.filter(id=new_item.id).update(
            date=now_dt - datetime.timedelta(minutes=10)
        )

        with mock.patch('simo.generic.controllers.timezone.now', autospec=True, return_value=now_dt):
            moisture = self.comp.controller._update_estimated_moisture()

        self.assertGreater(moisture, 50)
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.config['estimated_moisture'], moisture)
        self.assertEqual(
            self.comp.meta['last_weather_dt_processed'],
            int(now_dt.timestamp())
        )

    def test_contours_update_preserves_switch_and_occupation_data(self):
        self.comp.controller.contours_update([
            {'uid': 'c1', 'runtime': 7},
            {'uid': 'c2', 'runtime': 8},
        ])

        self.comp.refresh_from_db()
        self.assertEqual(
            self.comp.config['contours'],
            [
                {'uid': 'c1', 'switch': self.s1.id, 'runtime': 7, 'occupation': 100},
                {'uid': 'c2', 'switch': self.s2.id, 'runtime': 8, 'occupation': 100},
            ],
        )
        self.assertEqual(self.comp.config['program']['duration'], 14)

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

    def test_perform_schedule_handles_each_slot_only_once_within_gap(self):
        from simo.generic.controllers import Watering

        self.comp.config['schedule'] = {
            'mode': 'daily',
            'daily': ['10:00'],
            'weekly': {str(i): [] for i in range(1, 8)},
        }
        self.comp.value = {'status': 'stopped', 'program_progress': 0}
        self.comp.meta = {}
        self.comp.save(update_fields=['config', 'value', 'meta'])

        dt = timezone.make_aware(datetime.datetime(2024, 1, 1, 10, 10, 0), pytz.utc)
        slot_ts = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 10 * 3600

        with (
            mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt),
            mock.patch.object(Watering, 'reset', autospec=True) as reset,
            mock.patch.object(Watering, 'start', autospec=True) as start,
        ):
            self.comp.controller._perform_schedule()
            self.comp.controller._perform_schedule()

        reset.assert_called_once()
        start.assert_called_once()
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.meta.get('last_scheduled_slot_ts'), slot_ts)

    def test_perform_schedule_weekly_keeps_midnight_grace_window(self):
        from simo.generic.controllers import Watering

        self.comp.config['schedule'] = {
            'mode': 'weekly',
            'daily': [],
            'weekly': {str(i): [] for i in range(1, 8)},
        }
        self.comp.config['schedule']['weekly']['1'] = ['23:50']
        self.comp.value = {'status': 'stopped', 'program_progress': 0}
        self.comp.meta = {}
        self.comp.save(update_fields=['config', 'value', 'meta'])

        dt = timezone.make_aware(datetime.datetime(2024, 1, 2, 0, 5, 0), pytz.utc)
        slot_ts = dt.replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp() - 10 * 60

        with (
            mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt),
            mock.patch.object(Watering, 'reset', autospec=True) as reset,
            mock.patch.object(Watering, 'start', autospec=True) as start,
        ):
            self.comp.controller._perform_schedule()

        reset.assert_called_once()
        start.assert_called_once()
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.meta.get('last_scheduled_slot_ts'), slot_ts)

    def test_perform_schedule_applies_scaled_program_for_scheduled_run(self):
        from simo.generic.controllers import Watering

        self.comp.config['schedule'] = {
            'mode': 'daily',
            'daily': ['10:00'],
            'weekly': {str(i): [] for i in range(1, 8)},
        }
        self.comp.config['estimated_moisture'] = 80
        self.comp.value = {'status': 'stopped', 'program_progress': 0}
        self.comp.meta = {}
        self.comp.save(update_fields=['config', 'value', 'meta'])

        dt = timezone.make_aware(datetime.datetime(2024, 1, 1, 10, 10, 0), pytz.utc)

        with (
            mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt),
            mock.patch.object(Watering, '_update_estimated_moisture', autospec=True, return_value=80),
            mock.patch.object(Watering, '_get_scheduled_runtime_multiplier', autospec=True, return_value=(0.5, 'estimated_moisture')),
            mock.patch.object(Watering, 'reset', autospec=True) as reset,
            mock.patch.object(Watering, 'start', autospec=True) as start,
        ):
            self.comp.controller._perform_schedule()

        reset.assert_called_once_with(self.comp.controller, restore_base=False)
        start.assert_called_once_with(self.comp.controller, scheduled=True)
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.config['program']['duration'], 4)
        self.assertEqual(self.comp.meta.get('active_program_multiplier'), 0.5)
        self.assertEqual(self.comp.meta.get('active_program_source'), 'scheduled_ai')

    def test_perform_schedule_marks_busy_slot_as_handled_without_restart(self):
        from simo.generic.controllers import Watering

        self.comp.config['schedule'] = {
            'mode': 'daily',
            'daily': ['10:00'],
            'weekly': {str(i): [] for i in range(1, 8)},
        }
        self.comp.value = {'status': 'paused_program', 'program_progress': 2}
        self.comp.meta = {}
        self.comp.save(update_fields=['config', 'value', 'meta'])

        dt = timezone.make_aware(datetime.datetime(2024, 1, 1, 10, 10, 0), pytz.utc)
        slot_ts = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 10 * 3600

        with (
            mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt),
            mock.patch.object(Watering, 'reset', autospec=True) as reset,
            mock.patch.object(Watering, 'start', autospec=True) as start,
        ):
            self.comp.controller._perform_schedule()

        reset.assert_not_called()
        start.assert_not_called()
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.meta.get('last_scheduled_slot_ts'), slot_ts)

        self.comp.value = {'status': 'stopped', 'program_progress': 0}
        self.comp.save(update_fields=['value'])

        with (
            mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt),
            mock.patch.object(Watering, 'reset', autospec=True) as reset,
            mock.patch.object(Watering, 'start', autospec=True) as start,
        ):
            self.comp.controller._perform_schedule()

        reset.assert_not_called()
        start.assert_not_called()

    def test_perform_schedule_restores_orphaned_scheduled_program_when_stopped(self):
        effective_contours = self.comp.controller._get_effective_contours(0.5)
        effective_program = self.comp.controller._build_program(effective_contours)
        self.comp.config['program'] = effective_program
        self.comp.meta.update({
            'active_program_multiplier': 0.5,
            'active_program_source': 'scheduled_ai',
        })
        self.comp.value = {'status': 'stopped', 'program_progress': 0}
        self.comp.save(update_fields=['config', 'meta', 'value'])

        self.comp.controller._perform_schedule()

        self.comp.refresh_from_db()
        self.assertEqual(self.comp.config['program']['duration'], 10)
        self.assertNotIn('active_program_multiplier', self.comp.meta)
        self.assertNotIn('active_program_source', self.comp.meta)

    def test_perform_schedule_zero_multiplier_marks_slot_without_starting(self):
        from simo.generic.controllers import Watering

        self.comp.config['schedule'] = {
            'mode': 'daily',
            'daily': ['10:00'],
            'weekly': {str(i): [] for i in range(1, 8)},
        }
        self.comp.value = {'status': 'stopped', 'program_progress': 0}
        self.comp.meta = {}
        self.comp.save(update_fields=['config', 'value', 'meta'])

        dt = timezone.make_aware(datetime.datetime(2024, 1, 1, 10, 10, 0), pytz.utc)
        slot_ts = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 10 * 3600

        with (
            mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=dt),
            mock.patch.object(Watering, '_update_estimated_moisture', autospec=True, return_value=80),
            mock.patch.object(Watering, '_get_scheduled_runtime_multiplier', autospec=True, return_value=(0.0, 'estimated_moisture')),
            mock.patch.object(Watering, 'reset', autospec=True) as reset,
            mock.patch.object(Watering, 'start', autospec=True) as start,
        ):
            self.comp.controller._perform_schedule()

        reset.assert_not_called()
        start.assert_not_called()
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.meta.get('last_scheduled_slot_ts'), slot_ts)
        self.assertEqual(self.comp.config['program']['duration'], 10)

    def test_reset_restores_base_program_after_scaled_scheduled_run(self):
        effective_contours = self.comp.controller._get_effective_contours(0.5)
        effective_program = self.comp.controller._build_program(effective_contours)
        self.comp.config['program'] = effective_program
        self.comp.meta.update({
            'active_program_multiplier': 0.5,
            'active_program_source': 'scheduled_ai',
        })
        self.comp.config['estimated_moisture'] = 50
        self.comp.value = {'status': 'paused_program', 'program_progress': 2}
        self.comp.save(update_fields=['config', 'meta', 'value'])

        self.comp.controller.reset()

        self.comp.refresh_from_db()
        self.assertEqual(self.comp.value, {'status': 'stopped', 'program_progress': 0})
        self.assertEqual(self.comp.config['program']['duration'], 10)
        self.assertNotIn('active_program_multiplier', self.comp.meta)
        self.assertNotIn('active_program_source', self.comp.meta)
        self.assertGreater(self.comp.config['estimated_moisture'], 50)
