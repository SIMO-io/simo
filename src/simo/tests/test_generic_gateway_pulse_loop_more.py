import threading

from unittest import mock

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class FakeMqttClient:
    def username_pw_set(self, *_args, **_kwargs):
        return None

    def reconnect_delay_set(self, **_kwargs):
        return None


class GenericGatewayPulseLoopMoreTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.generic.gateways import GenericGatewayHandler
        from simo.generic.controllers import SwitchGroup

        self.SwitchGroup = SwitchGroup
        self.gw, _ = Gateway.objects.get_or_create(type=GenericGatewayHandler.uid)

    def _mk_handler(self):
        from simo.generic.gateways import GenericGatewayHandler

        with mock.patch('simo.core.gateways.mqtt.Client', autospec=True, return_value=FakeMqttClient()):
            handler = GenericGatewayHandler(self.gw)
        handler.logger = mock.Mock()
        return handler

    def _mk_switch(self, *, pulse=None):
        return Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=self.SwitchGroup.uid,
            config={},
            meta={'pulse': pulse} if pulse else {},
            value=False,
        )

    def test_watch_switch_pulses_initializes_pulsing_switches(self):
        handler = self._mk_handler()
        comp = self._mk_switch(pulse={'frame': 1.0, 'duty': 0.5})

        calls = []

        def _send(self, value):
            calls.append((self.component.id, value))

        exit_event = threading.Event()

        def fake_sleep(_dt):
            exit_event.set()

        with (
            mock.patch('simo.generic.gateways.time.sleep', autospec=True, side_effect=fake_sleep),
            mock.patch('simo.generic.gateways.time.time', autospec=True, return_value=0.0),
            mock.patch('simo.core.controllers.Switch.send', autospec=True, side_effect=_send),
        ):
            handler.watch_switch_pulses(exit_event)

        self.assertIn(comp.id, handler.pulsing_switches)
        self.assertEqual(calls, [(comp.id, True)])

    def test_watch_switch_pulses_toggles_false_then_true(self):
        handler = self._mk_handler()
        comp = self._mk_switch(pulse={'frame': 1.0, 'duty': 0.5})

        calls = []

        def _send(self, value):
            calls.append((self.component.id, value))

        exit_event = threading.Event()
        now = {'t': 0.0}
        sleep_calls = {'n': 0}

        def fake_time():
            return now['t']

        def fake_sleep(dt):
            now['t'] += dt
            sleep_calls['n'] += 1
            if sleep_calls['n'] >= 6:
                exit_event.set()

        with (
            mock.patch('simo.generic.gateways.time.sleep', autospec=True, side_effect=fake_sleep),
            mock.patch('simo.generic.gateways.time.time', autospec=True, side_effect=fake_time),
            mock.patch('simo.core.controllers.Switch.send', autospec=True, side_effect=_send),
        ):
            handler.watch_switch_pulses(exit_event)

        # Initial True, then should toggle to False and back True.
        self.assertIn((comp.id, True), calls)
        self.assertIn((comp.id, False), calls)
        self.assertGreaterEqual(calls.count((comp.id, True)), 2)

    def test_watch_switch_pulses_removes_switch_when_pulse_removed(self):
        handler = self._mk_handler()
        comp = self._mk_switch(pulse={'frame': 1.0, 'duty': 0.5})

        exit_event = threading.Event()
        now = {'t': 0.0}

        def fake_time():
            return now['t']

        def fake_sleep(dt):
            now['t'] += dt
            # After first loop, remove pulse from DB.
            if now['t'] >= 0.3 and comp.meta.get('pulse'):
                comp.meta.pop('pulse', None)
                comp.save(update_fields=['meta'])
            if now['t'] >= 0.6:
                exit_event.set()

        with (
            mock.patch('simo.generic.gateways.time.sleep', autospec=True, side_effect=fake_sleep),
            mock.patch('simo.generic.gateways.time.time', autospec=True, side_effect=fake_time),
            mock.patch('simo.core.controllers.Switch.send', autospec=True),
        ):
            handler.watch_switch_pulses(exit_event)

        self.assertNotIn(comp.id, handler.pulsing_switches)

    def test_watch_switch_pulses_updates_pulse_when_changed(self):
        handler = self._mk_handler()
        comp = self._mk_switch(pulse={'frame': 1.0, 'duty': 0.5})

        exit_event = threading.Event()
        now = {'t': 0.0}

        def fake_time():
            return now['t']

        def fake_sleep(dt):
            now['t'] += dt
            if now['t'] >= 0.3 and comp.meta.get('pulse', {}).get('frame') == 1.0:
                comp.meta['pulse'] = {'frame': 2.0, 'duty': 0.25}
                comp.save(update_fields=['meta'])
            if now['t'] >= 0.6:
                exit_event.set()

        with (
            mock.patch('simo.generic.gateways.time.sleep', autospec=True, side_effect=fake_sleep),
            mock.patch('simo.generic.gateways.time.time', autospec=True, side_effect=fake_time),
            mock.patch('simo.core.controllers.Switch.send', autospec=True),
        ):
            handler.watch_switch_pulses(exit_event)

        self.assertEqual(handler.pulsing_switches[comp.id]['pulse']['frame'], 2.0)

    def test_watch_switch_pulses_resync_adds_new_pulsing_switch(self):
        handler = self._mk_handler()
        comp1 = self._mk_switch(pulse={'frame': 1.0, 'duty': 0.5})
        comp2 = self._mk_switch(pulse=None)

        calls = []

        def _send(self, value):
            calls.append((self.component.id, value))

        exit_event = threading.Event()
        now = {'t': 0.0}
        loops = {'n': 0}

        def fake_time():
            return now['t']

        def fake_sleep(dt):
            now['t'] += dt
            loops['n'] += 1
            # Before resync (40 loops), turn on pulse for comp2.
            if loops['n'] == 10:
                comp2.meta['pulse'] = {'frame': 1.0, 'duty': 0.5}
                comp2.save(update_fields=['meta'])
            if loops['n'] >= 41:
                exit_event.set()

        with (
            mock.patch('simo.generic.gateways.time.sleep', autospec=True, side_effect=fake_sleep),
            mock.patch('simo.generic.gateways.time.time', autospec=True, side_effect=fake_time),
            mock.patch('simo.core.controllers.Switch.send', autospec=True, side_effect=_send),
        ):
            handler.watch_switch_pulses(exit_event)

        self.assertIn(comp1.id, handler.pulsing_switches)
        self.assertIn(comp2.id, handler.pulsing_switches)
        self.assertIn((comp2.id, True), calls)

