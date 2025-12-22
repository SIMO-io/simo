import time
from types import SimpleNamespace
from unittest import mock

from django.utils import timezone

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class FakeMqttClient:
    def __init__(self):
        self.on_connect = None
        self.on_message = None

    def username_pw_set(self, *_args, **_kwargs):
        return None

    def reconnect_delay_set(self, **_kwargs):
        return None


class GenericGatewayPeriodicTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.generic.gateways import DummyGatewayHandler, GenericGatewayHandler

        self.dummy_gw, _ = Gateway.objects.get_or_create(type=DummyGatewayHandler.uid)
        self.generic_gw, _ = Gateway.objects.get_or_create(type=GenericGatewayHandler.uid)

    def _mk_generic_handler(self):
        from simo.generic.gateways import GenericGatewayHandler

        with mock.patch('simo.core.gateways.mqtt.Client', autospec=True, side_effect=FakeMqttClient):
            handler = GenericGatewayHandler(self.generic_gw)
        handler.logger = mock.Mock()
        return handler

    def test_dummy_gateway_perform_value_send_calls_controller_set(self):
        from simo.generic.controllers import DummySwitch
        from simo.generic.gateways import DummyGatewayHandler

        comp = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.dummy_gw,
            base_type='switch',
            controller_uid=DummySwitch.uid,
            config={},
            meta={},
            value=False,
        )

        with mock.patch('simo.core.gateways.mqtt.Client', autospec=True, side_effect=FakeMqttClient):
            handler = DummyGatewayHandler(self.dummy_gw)

        handler.logger = mock.Mock()
        comp.controller.set = mock.Mock()
        handler.perform_value_send(comp, True)
        comp.controller.set.assert_called_once_with(True)

    def test_generic_watch_timers_triggers_timer_end(self):
        from simo.generic.controllers import DummySwitch

        comp = Component.objects.create(
            name='T',
            zone=self.zone,
            category=None,
            gateway=self.dummy_gw,
            base_type='switch',
            controller_uid=DummySwitch.uid,
            config={},
            meta={
                'timer_to': time.time() - 1,
                'timer_start': time.time() - 10,
                'timer_event': 'toggle',
            },
            value=False,
        )

        handler = self._mk_generic_handler()

        with mock.patch('simo.core.controllers.Switch.toggle', autospec=True) as toggle:
            handler.watch_timers()
        toggle.assert_called_once()

        comp.refresh_from_db()
        self.assertEqual(comp.meta.get('timer_to'), 0)
        self.assertEqual(comp.meta.get('timer_start'), 0)

    def test_generic_watch_timers_skips_future_timers(self):
        from simo.generic.controllers import DummySwitch

        Component.objects.create(
            name='T',
            zone=self.zone,
            category=None,
            gateway=self.dummy_gw,
            base_type='switch',
            controller_uid=DummySwitch.uid,
            config={},
            meta={
                'timer_to': time.time() + 500,
                'timer_start': time.time(),
                'timer_event': 'toggle',
            },
            value=False,
        )

        handler = self._mk_generic_handler()
        with mock.patch('simo.core.controllers.Switch.toggle', autospec=True) as toggle:
            handler.watch_timers()
        toggle.assert_not_called()

    def test_generic_watch_watering_running_program_increments_progress(self):
        from simo.generic.controllers import Watering

        Component.objects.create(
            name='W',
            zone=self.zone,
            category=None,
            gateway=self.generic_gw,
            base_type='watering',
            controller_uid=Watering.uid,
            config={'program': {'duration': 10, 'flow': []}, 'schedule': {}},
            meta={},
            value={'status': 'running_program', 'program_progress': 3},
        )
        handler = self._mk_generic_handler()

        with mock.patch('simo.generic.controllers.Watering._set_program_progress', autospec=True) as prog:
            handler.watch_watering()
        prog.assert_called_once()
        self.assertEqual(prog.call_args.args[1], 4)

    def test_generic_watch_watering_not_running_calls_perform_schedule(self):
        from simo.generic.controllers import Watering

        Component.objects.create(
            name='W',
            zone=self.zone,
            category=None,
            gateway=self.generic_gw,
            base_type='watering',
            controller_uid=Watering.uid,
            config={'program': {'duration': 10, 'flow': []}, 'schedule': {}},
            meta={},
            value={'status': 'stopped', 'program_progress': 0},
        )
        handler = self._mk_generic_handler()

        with mock.patch('simo.generic.controllers.Watering._perform_schedule', autospec=True) as sched:
            handler.watch_watering()
        sched.assert_called_once()

    def test_generic_low_battery_notifications_skips_early_hour(self):
        handler = self._mk_generic_handler()
        role = mk_role(self.inst, is_owner=True, is_superuser=True)
        user = mk_user('o@example.com', 'O')
        mk_instance_user(user, self.inst, role)

        Component.objects.create(
            name='B',
            zone=self.zone,
            category=None,
            gateway=self.generic_gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
            battery_level=10,
        )

        with (
            mock.patch('simo.generic.gateways.timezone.localtime', autospec=True, return_value=SimpleNamespace(hour=6)),
            mock.patch('simo.notifications.utils.notify_users', autospec=True) as notify,
            mock.patch('simo.automation.helpers.be_or_not_to_be', autospec=True, return_value=True),
        ):
            handler.low_battery_notifications()
        notify.assert_not_called()

    def test_generic_low_battery_notifications_notifies_and_updates_meta(self):
        handler = self._mk_generic_handler()
        role = mk_role(self.inst, is_owner=True, is_superuser=True)
        user = mk_user('o2@example.com', 'O2')
        mk_instance_user(user, self.inst, role)

        comp = Component.objects.create(
            name='B',
            zone=self.zone,
            category=None,
            gateway=self.generic_gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
            battery_level=10,
        )

        with (
            mock.patch('simo.generic.gateways.timezone.localtime', autospec=True, return_value=SimpleNamespace(hour=8)),
            mock.patch('simo.notifications.utils.notify_users', autospec=True) as notify,
            mock.patch('simo.automation.helpers.be_or_not_to_be', autospec=True, return_value=True),
        ):
            handler.low_battery_notifications()

        notify.assert_called_once()
        comp.refresh_from_db()
        self.assertGreater(comp.meta.get('last_battery_warning', 0), 0)

    def test_generic_watch_thermostats_calls_evaluate(self):
        from simo.generic.controllers import Thermostat

        Component.objects.create(
            name='TH',
            zone=self.zone,
            category=None,
            gateway=self.generic_gw,
            base_type='thermostat',
            controller_uid=Thermostat.uid,
            config={},
            meta={},
            value=None,
        )
        handler = self._mk_generic_handler()

        with (
            mock.patch('simo.generic.gateways.timezone.activate', autospec=True),
            mock.patch('simo.generic.controllers.Thermostat._evaluate', autospec=True) as eval_,
        ):
            handler.watch_thermostats()

        eval_.assert_called_once()
