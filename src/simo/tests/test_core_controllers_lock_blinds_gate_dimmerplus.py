from unittest import mock

from django.core.exceptions import ValidationError

from simo.core.controllers import BEFORE_SEND, BEFORE_SET
from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance, mk_user


class DimmerPlusControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.gateways import GenericGatewayHandler
        from simo.core.controllers import DimmerPlus as BaseDimmerPlus

        class TestDimmerPlus(BaseDimmerPlus):
            gateway_class = GenericGatewayHandler

        self.DimmerPlus = TestDimmerPlus
        self.comp = Component.objects.create(
            name='DP',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='dimmer-plus',
            controller_uid=TestDimmerPlus.uid,
            config={'main_min': 0.0, 'main_max': 1.0, 'secondary_min': 0.0, 'secondary_max': 1.0},
            meta={},
            value={'main': 0.2, 'secondary': 0.3},
        )

    def test_validate_fills_missing_channels_from_current_value(self):
        ctrl = self.DimmerPlus(self.comp)
        out = ctrl._validate_val({'main': 0.5})
        self.assertEqual(out['main'], 0.5)
        self.assertEqual(out['secondary'], 0.3)

        out = ctrl._validate_val({'secondary': 0.8})
        self.assertEqual(out['main'], 0.2)
        self.assertEqual(out['secondary'], 0.8)

    def test_validate_rejects_empty_payload(self):
        ctrl = self.DimmerPlus(self.comp)
        with self.assertRaises(ValidationError):
            ctrl._validate_val({})

    def test_validate_rejects_out_of_bounds(self):
        ctrl = self.DimmerPlus(self.comp)
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'main': 2.0})
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'main': -1.0})
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'secondary': 2.0})
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'secondary': -1.0})

    def test_validate_uses_middle_secondary_when_no_current_value(self):
        self.comp.value = None
        self.comp.value_previous = None
        self.comp.save(update_fields=['value', 'value_previous'])

        ctrl = self.DimmerPlus(self.comp)
        out = ctrl._validate_val({'main': 0.5})
        self.assertEqual(out['secondary'], 0.5)

    def test_toggle_routes_by_main_channel(self):
        ctrl = self.DimmerPlus(self.comp)

        with (
            mock.patch.object(self.DimmerPlus, 'turn_off', autospec=True) as off,
            mock.patch.object(self.DimmerPlus, 'turn_on', autospec=True) as on,
        ):
            self.comp.value = {'main': 0.1, 'secondary': 0.0}
            self.comp.save(update_fields=['value'])
            ctrl.toggle()
        off.assert_called_once()
        on.assert_not_called()

        with (
            mock.patch.object(self.DimmerPlus, 'turn_off', autospec=True) as off,
            mock.patch.object(self.DimmerPlus, 'turn_on', autospec=True) as on,
        ):
            self.comp.value = {'main': 0.0, 'secondary': 0.0}
            self.comp.save(update_fields=['value'])
            ctrl.toggle()
        on.assert_called_once()
        off.assert_not_called()

    def test_turn_on_sends_value_previous_when_value_is_unknown(self):
        self.comp.value = None
        self.comp.value_previous = {'main': 0.9, 'secondary': 0.1}
        self.comp.save(update_fields=['value', 'value_previous'])

        ctrl = self.DimmerPlus(self.comp)
        with mock.patch.object(self.DimmerPlus, 'send', autospec=True) as send:
            ctrl.turn_on()
        send.assert_called_once_with(ctrl, {'main': 0.9, 'secondary': 0.1})


class LockControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.gateways import GenericGatewayHandler
        from simo.core.controllers import Lock as BaseLock

        class TestLock(BaseLock):
            gateway_class = GenericGatewayHandler

        self.Lock = TestLock
        self.comp = Component.objects.create(
            name='L',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='lock',
            controller_uid=TestLock.uid,
            config={},
            meta={},
            value='unlocked',
        )

    def test_receive_from_device_maps_bool_and_int_values(self):
        ctrl = self.Lock(self.comp)
        from simo.core.controllers import ControllerBase

        captured = []

        def _capture(self_controller, value, *args, **kwargs):
            captured.append(value)
            return value

        with mock.patch.object(ControllerBase, '_receive_from_device', autospec=True, side_effect=_capture):
            ctrl._receive_from_device(True)
            ctrl._receive_from_device(False)
            ctrl._receive_from_device(ctrl.LOCKED)

        self.assertEqual(captured, ['locked', 'unlocked', 'locked'])

    def test_validate_enforces_bool_before_send(self):
        ctrl = self.Lock(self.comp)
        with self.assertRaises(ValidationError):
            ctrl._validate_val('x', occasion=BEFORE_SEND)

    def test_validate_rejects_unknown_state_before_set(self):
        ctrl = self.Lock(self.comp)
        with self.assertRaises(ValidationError):
            ctrl._validate_val('nope', occasion=BEFORE_SET)

    def test_set_records_actor_when_transitioning(self):
        ctrl = self.Lock(self.comp)
        actor = mk_user('a@example.com', 'A')

        ctrl.set('locking', actor=actor)
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.change_init_by_id, actor.id)
        self.assertIsNotNone(self.comp.change_init_date)

        ctrl.set('unlocking', actor=actor)
        self.comp.refresh_from_db()
        self.assertEqual(self.comp.change_init_by_id, actor.id)


class BlindsControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.gateways import GenericGatewayHandler
        from simo.core.controllers import Blinds as BaseBlinds

        class TestBlinds(BaseBlinds):
            gateway_class = GenericGatewayHandler

        self.Blinds = TestBlinds
        self.comp = Component.objects.create(
            name='B',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='blinds',
            controller_uid=TestBlinds.uid,
            config={'open_duration': 5, 'control_mode': 'slide'},
            meta={},
            value={'target': 0, 'position': 0, 'angle': 30},
        )

    def test_validate_before_send_supports_legacy_numeric_targets(self):
        ctrl = self.Blinds(self.comp)
        out = ctrl._validate_val(100.9, occasion=BEFORE_SEND)
        self.assertEqual(out['target'], 100)
        self.assertEqual(out['angle'], 30)

    def test_validate_before_send_adds_default_angle_when_missing(self):
        ctrl = self.Blinds(self.comp)
        out = ctrl._validate_val({'target': 1}, occasion=BEFORE_SEND)
        self.assertEqual(out['angle'], 30)

    def test_validate_before_send_rejects_bad_angle(self):
        ctrl = self.Blinds(self.comp)
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'target': 1, 'angle': 'x'}, occasion=BEFORE_SEND)
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'target': 1, 'angle': 999}, occasion=BEFORE_SEND)

    def test_validate_before_set_fills_missing_keys_and_rejects_bad_position(self):
        ctrl = self.Blinds(self.comp)

        out = ctrl._validate_val({'position': 10}, occasion=BEFORE_SET)
        self.assertEqual(out['target'], 0)
        self.assertEqual(out['position'], 10)
        self.assertEqual(out['angle'], 30)

        with self.assertRaises(ValidationError):
            ctrl._validate_val('not-a-dict', occasion=BEFORE_SET)
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'x': 1}, occasion=BEFORE_SET)
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'position': -1}, occasion=BEFORE_SET)
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'position': 999999}, occasion=BEFORE_SET)

    def test_validate_before_send_rejects_too_large_target(self):
        ctrl = self.Blinds(self.comp)
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'target': 999999}, occasion=BEFORE_SEND)

    def test_validate_before_send_rejects_bad_target_type(self):
        ctrl = self.Blinds(self.comp)
        with self.assertRaises(ValidationError):
            ctrl._validate_val({'target': 'x'}, occasion=BEFORE_SEND)

    def test_open_close_stop_include_angle_when_valid(self):
        ctrl = self.Blinds(self.comp)
        sent = []

        def _capture(_self, value):
            sent.append(value)

        with mock.patch.object(self.Blinds, 'send', autospec=True, side_effect=_capture):
            ctrl.open()
            ctrl.close()
            ctrl.stop()

        self.assertEqual(sent[0], {'target': 0, 'angle': 30})
        self.assertEqual(sent[1], {'target': 5000, 'angle': 30})
        self.assertEqual(sent[2], {'target': -1, 'angle': 30})

    def test_open_close_stop_omit_angle_when_invalid(self):
        self.comp.value['angle'] = 999
        self.comp.save(update_fields=['value'])

        ctrl = self.Blinds(self.comp)
        sent = []

        def _capture(_self, value):
            sent.append(value)

        with mock.patch.object(self.Blinds, 'send', autospec=True, side_effect=_capture):
            ctrl.open()
            ctrl.close()
            ctrl.stop()

        self.assertEqual(sent[0], {'target': 0})
        self.assertEqual(sent[1], {'target': 5000})
        self.assertEqual(sent[2], {'target': -1})


class GateControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.gateways import GenericGatewayHandler
        from simo.core.controllers import Gate as BaseGate

        class TestGate(BaseGate):
            gateway_class = GenericGatewayHandler

        self.Gate = TestGate
        self.comp = Component.objects.create(
            name='G',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='gate',
            controller_uid=TestGate.uid,
            config={'action_method': 'click'},
            meta={},
            value='closed',
        )

    def test_validate_send_respects_click_mode(self):
        ctrl = self.Gate(self.comp)
        with self.assertRaises(ValidationError):
            ctrl._validate_val('open', occasion=BEFORE_SEND)
        self.assertEqual(ctrl._validate_val('call', occasion=BEFORE_SEND), 'call')

    def test_validate_send_allows_open_close_in_non_click_mode(self):
        self.comp.config['action_method'] = 'direct'
        self.comp.save(update_fields=['config'])
        ctrl = self.Gate(self.comp)

        self.assertEqual(ctrl._validate_val('open', occasion=BEFORE_SEND), 'open')
        self.assertEqual(ctrl._validate_val('close', occasion=BEFORE_SEND), 'close')
        self.assertEqual(ctrl._validate_val('call', occasion=BEFORE_SEND), 'call')
        with self.assertRaises(ValidationError):
            ctrl._validate_val('nope', occasion=BEFORE_SEND)

    def test_validate_set_rejects_unknown_state(self):
        ctrl = self.Gate(self.comp)
        with self.assertRaises(ValidationError):
            ctrl._validate_val('unknown', occasion=BEFORE_SET)

    def test_validate_set_accepts_known_states(self):
        ctrl = self.Gate(self.comp)
        for state in ('closed', 'open', 'open_moving', 'closed_moving'):
            self.assertEqual(ctrl._validate_val(state, occasion=BEFORE_SET), state)

    def test_is_in_alarm_flags_closed_states(self):
        ctrl = self.Gate(self.comp)
        self.comp.value = 'closed'
        self.assertTrue(ctrl.is_in_alarm())
        self.comp.value = 'closed_moving'
        self.assertTrue(ctrl.is_in_alarm())
        self.comp.value = 'open'
        self.assertFalse(ctrl.is_in_alarm())
        self.comp.value = 'open_moving'
        self.assertFalse(ctrl.is_in_alarm())

        self.comp.value = None
        self.assertFalse(ctrl.is_in_alarm())

    def test_open_close_call_delegate_to_send(self):
        ctrl = self.Gate(self.comp)
        with mock.patch.object(self.Gate, 'send', autospec=True) as send:
            ctrl.call()
        send.assert_called_once_with(ctrl, 'call')

    def test_open_close_delegate_to_send_in_direct_mode(self):
        self.comp.config['action_method'] = 'direct'
        self.comp.save(update_fields=['config'])
        ctrl = self.Gate(self.comp)

        with mock.patch.object(self.Gate, 'send', autospec=True) as send:
            ctrl.open()
            ctrl.close()
        send.assert_any_call(ctrl, 'open')
        send.assert_any_call(ctrl, 'close')
