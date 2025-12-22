from unittest import mock

from django.core.exceptions import ValidationError

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class DimmerControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.controllers import DimmableLightsGroup

        self.comp = Component.objects.create(
            name='D',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='dimmer',
            controller_uid=DimmableLightsGroup.uid,
            config={'min': 0.0, 'max': 100.0, 'inverse': False},
            meta={},
            value=0,
        )

    def test_prepare_for_send_true_restores_previous_when_off(self):
        self.comp.value = 0
        self.comp.value_previous = 42
        self.comp.save(update_fields=['value', 'value_previous'])

        val = self.comp.controller._prepare_for_send(True)
        self.assertEqual(val, 42)

    def test_prepare_for_send_true_uses_max_when_no_previous(self):
        self.comp.value = 0
        self.comp.value_previous = None
        self.comp.save(update_fields=['value', 'value_previous'])

        val = self.comp.controller._prepare_for_send(True)
        self.assertEqual(val, 100.0)

    def test_prepare_for_send_false_is_zero(self):
        self.assertEqual(self.comp.controller._prepare_for_send(False), 0)

    def test_receive_from_device_converts_bool_to_numeric_levels(self):
        from simo.core.controllers import ControllerBase

        captured = []

        def _capture(self_controller, value, *args, **kwargs):
            captured.append(value)
            return value

        with mock.patch.object(ControllerBase, '_receive_from_device', autospec=True, side_effect=_capture):
            self.comp.controller._receive_from_device(True)
            self.comp.controller._receive_from_device(False)

        self.assertEqual(captured, [100.0, 0.0])


class RgbwLightControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.gateways import GenericGatewayHandler
        from simo.core.controllers import RGBWLight as BaseRGBWLight

        class TestRGBWLight(BaseRGBWLight):
            gateway_class = GenericGatewayHandler

        self.comp = Component.objects.create(
            name='L',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='rgbw-light',
            controller_uid=TestRGBWLight.uid,
            config={'has_white': False},
            meta={},
            value={'scenes': ['#ff0000'] * 5, 'active': 0, 'is_on': False},
        )
        self.ctrl = TestRGBWLight(self.comp)

    def test_validate_rejects_bad_color_length(self):
        with self.assertRaises(ValidationError):
            self.ctrl._validate_val({'scenes': ['#123'] * 5, 'active': 0, 'is_on': True})

    def test_validate_uses_existing_scenes_when_missing(self):
        out = self.ctrl._validate_val({'active': 1, 'is_on': True})
        self.assertEqual(out['scenes'], self.comp.value['scenes'])

    def test_validate_rejects_out_of_range_active(self):
        with self.assertRaises(Exception):
            self.ctrl._validate_val({'active': 99, 'is_on': True, 'scenes': ['#ff0000'] * 5})

    def test_has_white_enforces_9_char_colors(self):
        self.comp.config['has_white'] = True
        self.comp.value['scenes'] = ['#ff000000'] * 5
        self.comp.save(update_fields=['config', 'value'])
        self.ctrl.component = self.comp

        # Wrong length without white.
        with self.assertRaises(ValidationError):
            self.ctrl._validate_val({'active': 0, 'is_on': True, 'scenes': ['#ff0000'] * 5})


class SwitchAndMultiSwitchTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.controllers import SwitchGroup
        from simo.generic.gateways import GenericGatewayHandler
        from simo.core.controllers import DoubleSwitch as BaseDoubleSwitch

        class TestDoubleSwitch(BaseDoubleSwitch):
            gateway_class = GenericGatewayHandler

        self.switch = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        self.double = Component.objects.create(
            name='DS',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='double-switch',
            controller_uid=TestDoubleSwitch.uid,
            config={},
            meta={},
            value=[False, False],
        )
        self.double_ctrl = TestDoubleSwitch(self.double)

    def test_switch_click_schedules_turn_off_task(self):
        with (
            mock.patch('simo.core.controllers.Switch.turn_on', autospec=True),
            mock.patch('simo.core.tasks.component_action', autospec=True) as task,
        ):
            sig = mock.Mock()
            sig.apply_async = mock.Mock()
            task.s.return_value = sig
            self.switch.controller.click()

        task.s.assert_called_once_with(self.switch.id, 'turn_off')
        sig.apply_async.assert_called_once_with(countdown=1)

    def test_switch_turn_on_off_toggle_clear_pulse_meta(self):
        self.switch.meta['pulse'] = {'frame': 1, 'duty': 0.5}
        self.switch.save(update_fields=['meta'])

        with mock.patch('simo.core.controllers.Switch.send', autospec=True) as send:
            self.switch.controller.turn_on()
        self.switch.refresh_from_db()
        self.assertNotIn('pulse', self.switch.meta)
        send.assert_called_once_with(self.switch.controller, True)

        self.switch.meta['pulse'] = {'frame': 1, 'duty': 0.5}
        self.switch.value = True
        self.switch.save(update_fields=['meta', 'value'])

        with mock.patch('simo.core.controllers.Switch.send', autospec=True) as send:
            self.switch.controller.turn_off()
        self.switch.refresh_from_db()
        self.assertNotIn('pulse', self.switch.meta)
        send.assert_called_once_with(self.switch.controller, False)

        self.switch.meta['pulse'] = {'frame': 1, 'duty': 0.5}
        self.switch.value = False
        self.switch.save(update_fields=['meta', 'value'])

        with mock.patch('simo.core.controllers.Switch.send', autospec=True) as send:
            self.switch.controller.toggle()
        self.switch.refresh_from_db()
        self.assertNotIn('pulse', self.switch.meta)
        send.assert_called_once_with(self.switch.controller, True)

    def test_switch_pulse_sets_meta_and_publishes_to_generic_gateway(self):
        from simo.generic.gateways import GenericGatewayHandler
        from simo.core.models import Gateway

        Gateway.objects.get_or_create(type=GenericGatewayHandler.uid)

        import simo.core.controllers as core_controllers
        core_controllers.GatewayObjectCommand.publish.reset_mock()

        self.switch.controller.pulse(30, 50)
        self.switch.refresh_from_db()
        self.assertEqual(self.switch.meta['pulse'], {'frame': 30, 'duty': 0.5})
        core_controllers.GatewayObjectCommand.publish.assert_called_once()

    def test_multi_switch_validates_shape_and_types(self):
        with self.assertRaises(ValidationError):
            self.double_ctrl._validate_val(True)
        with self.assertRaises(ValidationError):
            self.double_ctrl._validate_val([True])
        with self.assertRaises(ValidationError):
            self.double_ctrl._validate_val([True, 'no'])

        ok = self.double_ctrl._validate_val([True, False])
        self.assertEqual(ok, [True, False])


class BulkSendTests(BaseSimoTestCase):
    def test_send_uses_bulk_send_for_switch_slaves(self):
        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        from simo.generic.controllers import SwitchGroup

        master = Component.objects.create(
            name='M',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        slave = Component.objects.create(
            name='S',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        master.slaves.add(slave)

        with mock.patch('simo.core.models.ComponentsManager.bulk_send', autospec=True) as bulk_send:
            master.controller.send(True)

        bulk_send.assert_called_once()
        sent_map = bulk_send.call_args.args[1]
        self.assertEqual(sent_map.get(master), True)
        self.assertEqual(sent_map.get(slave), True)
