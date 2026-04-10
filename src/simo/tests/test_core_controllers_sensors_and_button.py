from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError

from simo.core.models import Component, ComponentHistory, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance, mk_instance_user, mk_role, mk_user


class SensorControllersTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.generic.gateways import DummyGatewayHandler

        self.gw, _ = Gateway.objects.get_or_create(type=DummyGatewayHandler.uid)

    def test_dummy_numeric_sensor_validation_and_widget_choice(self):
        from simo.generic.controllers import DummyNumericSensor
        from simo.core.app_widgets import NumericSensorGraphWidget, NumericSensorWidget

        comp = Component.objects.create(
            name='N',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='numeric-sensor',
            controller_uid=DummyNumericSensor.uid,
            config={'widget': 'numeric-sensor-graph'},
            meta={},
            value=0,
        )

        self.assertIs(comp.controller.app_widget, NumericSensorGraphWidget)
        comp.config['widget'] = 'other'
        comp.save(update_fields=['config'])
        self.assertIs(comp.controller.app_widget, NumericSensorWidget)

        with self.assertRaises(ValidationError):
            comp.controller._validate_val('x')
        self.assertEqual(comp.controller._validate_val(1), 1)
        self.assertEqual(comp.controller._validate_val(Decimal('1.2')), Decimal('1.2'))

    def test_dummy_multi_sensor_validation_and_get_val(self):
        from simo.generic.controllers import DummyMultiSensor

        comp = Component.objects.create(
            name='M',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='multi-sensor',
            controller_uid=DummyMultiSensor.uid,
            config={},
            meta={},
            value=[['temperature', 21, 'C'], ['humidity', 40, '%'], ['motion', False, '']],
        )

        self.assertEqual(comp.controller.get_val('temperature'), 21)
        self.assertIsNone(comp.controller.get_val('nope'))

        with self.assertRaises(ValidationError):
            comp.controller._validate_val([["Value 1", 20, "%"]])
        with self.assertRaises(ValidationError):
            comp.controller._validate_val([["Value 1", 20, "%"], ["Value 2", 50, "C"], ["bad"]])

    def test_dummy_binary_sensor_validation(self):
        from simo.generic.controllers import DummyBinarySensor

        comp = Component.objects.create(
            name='B',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='binary-sensor',
            controller_uid=DummyBinarySensor.uid,
            config={},
            meta={},
            value=False,
        )
        self.assertEqual(comp.controller._validate_val(True), True)
        with self.assertRaises(ValidationError):
            comp.controller._validate_val(1)


class ButtonControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.generic.gateways import DummyGatewayHandler
        from simo.core.controllers import Button as BaseButton

        class TestButton(BaseButton):
            gateway_class = DummyGatewayHandler

        self.Button = TestButton
        self.gw, _ = Gateway.objects.get_or_create(type=DummyGatewayHandler.uid)
        self.button = Component.objects.create(
            name='BTN',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='button',
            controller_uid=TestButton.uid,
            config={},
            meta={},
            value='up',
        )

    def test_button_state_helpers(self):
        ctrl = self.Button(self.button)
        self.button.value = 'down'
        self.assertTrue(ctrl.is_down())
        self.assertFalse(ctrl.is_held())
        self.button.value = 'hold'
        self.assertTrue(ctrl.is_down())
        self.assertTrue(ctrl.is_held())

    def test_get_bonded_gear_returns_components_referencing_button(self):
        # Two components reference this button, one does not.
        c1 = Component.objects.create(
            name='C1',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={'controls': [{'button': self.button.id}]},
            meta={},
            value=False,
        )
        c2 = Component.objects.create(
            name='C2',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={'controls': [{'button': 999}, {'button': self.button.id}]},
            meta={},
            value=False,
        )
        Component.objects.create(
            name='C3',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

        ctrl = self.Button(self.button)
        gear = ctrl.get_bonded_gear()
        self.assertEqual({c.id for c in gear}, {c1.id, c2.id})

    def test_same_value_records_history_when_button_actor_changes(self):
        role = mk_role(self.inst)
        user1 = mk_user('user1@example.com', 'User 1')
        user2 = mk_user('user2@example.com', 'User 2')
        mk_instance_user(user1, self.inst, role)
        mk_instance_user(user2, self.inst, role)

        self.button.track_history = True
        self.button.value = 'down'
        self.button.save(update_fields=['track_history', 'value'])

        ComponentHistory.objects.create(
            component=self.button, type='value', value='down', user=user1
        )
        self.Button(self.button).set('down', actor=user1)
        self.assertEqual(ComponentHistory.objects.count(), 1)

        self.Button(self.button).set('down', actor=user2)
        self.assertEqual(ComponentHistory.objects.count(), 2)
        last_event = ComponentHistory.objects.order_by('-date', '-id').first()
        self.assertEqual(last_event.value, 'down')
        self.assertEqual(last_event.user, user2)


class OnOffPokerMixinTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.generic.gateways import DummyGatewayHandler
        from simo.generic.controllers import DummySwitch

        self.gw, _ = Gateway.objects.get_or_create(type=DummyGatewayHandler.uid)
        self.comp = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=DummySwitch.uid,
            config={},
            meta={},
            value=False,
        )

    def test_onoff_poker_mixin_toggles_between_turn_off_and_turn_on(self):
        from simo.core.controllers import OnOffPokerMixin

        calls = []

        class Poked(OnOffPokerMixin):
            def turn_on(self):
                calls.append('on')

            def turn_off(self):
                calls.append('off')

        p = Poked()
        p.poke()
        p.poke()
        self.assertEqual(calls, ['off', 'on'])

    def test_single_switch_validate_coerces_int_to_bool(self):
        self.assertEqual(self.comp.controller._validate_val(1), True)
        self.assertEqual(self.comp.controller._validate_val(0), False)
        with self.assertRaises(ValidationError):
            self.comp.controller._validate_val('nope')

    def test_same_value_does_not_record_extra_history_for_non_buttons(self):
        role = mk_role(self.inst)
        user1 = mk_user('switch1@example.com', 'Switch 1')
        user2 = mk_user('switch2@example.com', 'Switch 2')
        mk_instance_user(user1, self.inst, role)
        mk_instance_user(user2, self.inst, role)

        self.comp.track_history = True
        self.comp.value = False
        self.comp.save(update_fields=['track_history', 'value'])

        ComponentHistory.objects.create(
            component=self.comp, type='value', value=False, user=user1
        )
        self.comp.controller.set(False, actor=user2)
        self.assertEqual(ComponentHistory.objects.count(), 1)
