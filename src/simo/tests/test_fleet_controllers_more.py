from unittest import mock
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django import forms

from simo.core.models import Component, Gateway, Zone
from simo.fleet.models import Colonel, ColonelPin

from .base import (
    BaseSimoTestCase, mk_instance, mk_instance_user, mk_role, mk_user
)


class FleetControllersMoreTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.fleet.gateways import FleetGatewayHandler

        self.gw, _ = Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        self.colonel = Colonel.objects.create(
            instance=self.inst,
            uid='c-1',
            type='sentinel',
            firmware_version='1.0',
            enabled=True,
        )

    def _mk_component(self, *, controller_uid='x', base_type='switch', config=None, meta=None, value=None):
        cfg = {'colonel': self.colonel.id}
        if config:
            cfg.update(config)
        return Component.objects.create(
            name='C',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type=base_type,
            controller_uid=controller_uid,
            config=cfg,
            meta=meta or {},
            value=value,
        )

    def test_update_options_publishes_gateway_command(self):
        from simo.fleet.controllers import FleetDeviceMixin
        from simo.core.events import GatewayObjectCommand

        comp = self._mk_component(config={'colonel': self.colonel.id})
        ctrl = FleetDeviceMixin()
        ctrl.component = comp

        GatewayObjectCommand.publish.reset_mock()
        ctrl.update_options({'a': 1})

        GatewayObjectCommand.publish.assert_called_once()
        cmd_obj = GatewayObjectCommand.publish.call_args.args[0]
        self.assertEqual(cmd_obj.data.get('command'), 'update_options')
        self.assertEqual(cmd_obj.data.get('options'), {'a': 1})
        self.assertEqual(cmd_obj.data.get('id'), comp.id)

    def test_disable_controls_sets_controls_enabled_false(self):
        from simo.fleet.controllers import FleetDeviceMixin

        comp = self._mk_component(meta={'options': {}})
        ctrl = FleetDeviceMixin()
        ctrl.component = comp

        with mock.patch.object(ctrl, 'update_options', autospec=True) as upd:
            ctrl.disable_controls()
        upd.assert_called_once()
        self.assertEqual(upd.call_args.args[0]['controls_enabled'], False)

    def test_disable_controls_noop_when_already_disabled(self):
        from simo.fleet.controllers import FleetDeviceMixin

        comp = self._mk_component(meta={'options': {'controls_enabled': False}})
        ctrl = FleetDeviceMixin()
        ctrl.component = comp

        with mock.patch.object(ctrl, 'update_options', autospec=True) as upd:
            ctrl.disable_controls()
        upd.assert_not_called()

    def test_enable_controls_sets_controls_enabled_true(self):
        from simo.fleet.controllers import FleetDeviceMixin

        comp = self._mk_component(meta={'options': {'controls_enabled': False}})
        ctrl = FleetDeviceMixin()
        ctrl.component = comp

        with mock.patch.object(ctrl, 'update_options', autospec=True) as upd:
            ctrl.enable_controls()
        upd.assert_called_once()
        self.assertEqual(upd.call_args.args[0]['controls_enabled'], True)

    def test_enable_controls_noop_when_already_enabled(self):
        from simo.fleet.controllers import FleetDeviceMixin

        comp = self._mk_component(meta={'options': {'controls_enabled': True}})
        ctrl = FleetDeviceMixin()
        ctrl.component = comp

        with mock.patch.object(ctrl, 'update_options', autospec=True) as upd:
            ctrl.enable_controls()
        upd.assert_not_called()

    def test_call_cmd_publishes_call_command(self):
        from simo.fleet.controllers import FleetDeviceMixin
        from simo.core.events import GatewayObjectCommand

        comp = self._mk_component()
        ctrl = FleetDeviceMixin()
        ctrl.component = comp

        GatewayObjectCommand.publish.reset_mock()
        ctrl._call_cmd('reboot', 1, a=2)

        GatewayObjectCommand.publish.assert_called_once()
        cmd_obj = GatewayObjectCommand.publish.call_args.args[0]
        self.assertEqual(cmd_obj.data.get('command'), 'call')
        self.assertEqual(cmd_obj.data.get('method'), 'reboot')
        self.assertEqual(cmd_obj.data.get('args'), (1,))
        self.assertEqual(cmd_obj.data.get('kwargs'), {'a': 2})

    def test_get_colonel_config_uses_pin_no_for_colonel_pin_choice_field(self):
        from simo.fleet.controllers import FleetDeviceMixin
        from simo.fleet.forms import ColonelPinChoiceField

        class DummyForm(forms.Form):
            pin = ColonelPinChoiceField(queryset=ColonelPin.objects.none(), required=False)

        comp = self._mk_component(config={'pin': 'x', 'pin_no': 7, 'a': 1, 'b': None})
        ctrl = FleetDeviceMixin()
        ctrl.component = comp
        ctrl.config_form = DummyForm

        out = ctrl._get_colonel_config()
        self.assertEqual(out.get('pin_no'), 7)
        self.assertEqual(out.get('a'), 1)
        self.assertNotIn('pin', out)
        self.assertNotIn('b', out)
        self.assertNotIn('colonel', out)

    def test_dht_sensor_prepare_for_set_converts_to_fahrenheit(self):
        from simo.fleet.controllers import DHTSensor

        self.inst.units_of_measure = 'imperial'
        self.inst.save(update_fields=['units_of_measure'])

        comp = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='multi-sensor',
            controller_uid=DHTSensor.uid,
            config={'colonel': self.colonel.id, 'temperature_units': 'C'},
            meta={},
            value=[['temperature', 0, 'F'], ['humidity', 0, '%'], ['real_feel', 0, 'F']],
        )
        controller = DHTSensor(comp)
        out = controller._prepare_for_set({'temp': 10, 'hum': 50})
        self.assertEqual(out[0][1], 50.0)

    def test_bme680_occupied_pins_uses_interface_plus_100(self):
        from simo.fleet.controllers import BME680Sensor

        comp = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='multi-sensor',
            controller_uid=BME680Sensor.uid,
            config={'colonel': self.colonel.id},
            meta={},
            value=[],
        )
        ctrl = BME680Sensor(comp)

        with mock.patch('simo.fleet.controllers.get_i2c_interface_no', autospec=True, return_value=5):
            self.assertEqual(ctrl._get_occupied_pins(), [105])

    def test_mcp9808_default_value_units_uses_current_instance(self):
        from simo.fleet.controllers import MCP9808TempSensor

        comp = self._mk_component(controller_uid=MCP9808TempSensor.uid, base_type='numeric-sensor')
        ctrl = MCP9808TempSensor(comp)

        imperial_instance = mock.Mock(units_of_measure='imperial')
        with mock.patch('simo.fleet.controllers.get_current_instance', autospec=True, return_value=imperial_instance):
            self.assertEqual(ctrl.default_value_units, 'F')

    def test_room_presence_sensor_config_form_exposes_at_sens_choices(self):
        from simo.fleet.controllers import RoomPresenceSensor

        form = RoomPresenceSensor.config_form(controller_uid=RoomPresenceSensor.uid)

        self.assertIn('sens', form.fields)
        self.assertEqual(form.fields['sens'].initial, 10)
        self.assertEqual(
            [value for value, _label in form.fields['sens'].choices],
            list(range(1, 20)),
        )
        self.assertIn('range', form.fields)
        self.assertEqual(form.fields['range'].initial, 3.0)
        self.assertEqual(form.fields['range'].min_value, 1.0)
        self.assertEqual(form.fields['range'].max_value, 10.0)

    def test_room_presence_sensor_config_form_pushes_live_update_config(self):
        from simo.core.events import GatewayObjectCommand
        from simo.fleet.controllers import RoomPresenceSensor
        from simo.fleet.forms import RoomPresenceSensorConfigForm

        comp = self._mk_component(
            controller_uid=RoomPresenceSensor.uid,
            base_type='binary-sensor',
            config={'colonel': self.colonel.id, 'sens': 10, 'range': 3.0},
            value=False,
        )

        GatewayObjectCommand.publish.reset_mock()
        form = RoomPresenceSensorConfigForm(
            instance=comp,
            data={'sens': '14', 'range': '5.3'},
        )
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save()

        self.assertEqual(obj.config.get('sens'), 14)
        self.assertEqual(obj.config.get('range'), 5.3)
        GatewayObjectCommand.publish.assert_called_once()
        cmd_obj = GatewayObjectCommand.publish.call_args.args[0]
        self.assertEqual(cmd_obj.data.get('command'), 'call')
        self.assertEqual(cmd_obj.data.get('method'), 'update_config')
        self.assertEqual(cmd_obj.data.get('id'), comp.id)

    def test_room_presence_sensor_config_form_does_not_trigger_full_colonel_update(self):
        from simo.fleet.controllers import RoomPresenceSensor
        from simo.fleet.forms import RoomPresenceSensorConfigForm

        comp = self._mk_component(
            controller_uid=RoomPresenceSensor.uid,
            base_type='binary-sensor',
            config={'colonel': self.colonel.id, 'sens': 10, 'range': 3.0},
            value=False,
        )

        form = RoomPresenceSensorConfigForm(
            instance=comp,
            data={'sens': '12', 'range': '6.5'},
        )
        self.assertTrue(form.is_valid(), form.errors)

        with mock.patch('simo.fleet.models.Colonel.update_config', autospec=True) as update_config:
            form.save()

        update_config.assert_not_called()

    def test_sentinel_room_presence_recalibrate_publishes_call_command(self):
        from simo.core.events import GatewayObjectCommand
        from simo.core.serializers import ComponentSerializer
        from simo.fleet.controllers import RoomPresenceSensor

        comp = self._mk_component(
            controller_uid=RoomPresenceSensor.uid,
            base_type='binary-sensor',
            config={'colonel': self.colonel.id, 'sens': 10, 'range': 3.0},
            value=False,
        )
        ctrl = RoomPresenceSensor(comp)
        user = mk_user('room-super@simo.io', 'Room Super')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(user, self.inst, role)

        GatewayObjectCommand.publish.reset_mock()
        with mock.patch('simo.fleet.controllers.get_current_user', return_value=user):
            ctrl.recalibrate()

        GatewayObjectCommand.publish.assert_called_once()
        cmd_obj = GatewayObjectCommand.publish.call_args.args[0]
        self.assertEqual(cmd_obj.data.get('command'), 'call')
        self.assertEqual(cmd_obj.data.get('method'), 'recalibrate')
        self.assertEqual(cmd_obj.data.get('id'), comp.id)

        serializer = ComponentSerializer(
            instance=comp,
            context={
                'request': SimpleNamespace(
                    user=user,
                    path='/',
                    build_absolute_uri=lambda p: p,
                ),
                'instance': self.inst,
            },
        )
        self.assertIn('recalibrate', serializer.get_controller_methods(comp))

    def test_sentinel_room_presence_recalibrate_denied_for_non_superuser(self):
        from simo.core.events import GatewayObjectCommand
        from simo.core.serializers import ComponentSerializer
        from simo.fleet.controllers import RoomPresenceSensor

        comp = self._mk_component(
            controller_uid=RoomPresenceSensor.uid,
            base_type='binary-sensor',
            config={'colonel': self.colonel.id, 'sens': 10, 'range': 3.0},
            value=False,
        )
        ctrl = RoomPresenceSensor(comp)
        user = mk_user('room-regular@simo.io', 'Room Regular')
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(user, self.inst, role)

        GatewayObjectCommand.publish.reset_mock()
        with mock.patch('simo.fleet.controllers.get_current_user', return_value=user):
            with self.assertRaises(ValidationError):
                ctrl.recalibrate()

        GatewayObjectCommand.publish.assert_not_called()

        serializer = ComponentSerializer(
            instance=comp,
            context={
                'request': SimpleNamespace(
                    user=user,
                    path='/',
                    build_absolute_uri=lambda p: p,
                ),
                'instance': self.inst,
            },
        )
        self.assertNotIn('recalibrate', serializer.get_controller_methods(comp))

    def test_sentinel_air_quality_recalibrate_publishes_call_command(self):
        from simo.core.events import GatewayObjectCommand
        from simo.core.serializers import ComponentSerializer
        from simo.fleet.controllers import AirQualitySensor

        comp = self._mk_component(
            controller_uid=AirQualitySensor.uid,
            base_type='multi-sensor',
            value=[['TVOC', 120, 'ppb'], ['AQI (UBA)', 1, '']],
        )
        ctrl = AirQualitySensor(comp)
        user = mk_user('super@simo.io', 'Super')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(user, self.inst, role)

        GatewayObjectCommand.publish.reset_mock()
        with mock.patch('simo.fleet.controllers.get_current_user', return_value=user):
            ctrl.recalibrate()

        GatewayObjectCommand.publish.assert_called_once()
        cmd_obj = GatewayObjectCommand.publish.call_args.args[0]
        self.assertEqual(cmd_obj.data.get('command'), 'call')
        self.assertEqual(cmd_obj.data.get('method'), 'recalibrate')
        self.assertEqual(cmd_obj.data.get('id'), comp.id)

        serializer = ComponentSerializer(
            instance=comp,
            context={
                'request': SimpleNamespace(
                    user=user,
                    path='/',
                    build_absolute_uri=lambda p: p,
                ),
                'instance': self.inst,
            },
        )
        self.assertIn('recalibrate', serializer.get_controller_methods(comp))

    def test_sentinel_air_quality_recalibrate_denied_for_non_superuser(self):
        from simo.core.events import GatewayObjectCommand
        from simo.core.serializers import ComponentSerializer
        from simo.fleet.controllers import AirQualitySensor

        comp = self._mk_component(
            controller_uid=AirQualitySensor.uid,
            base_type='multi-sensor',
            value=[['TVOC', 120, 'ppb'], ['AQI (UBA)', 1, '']],
        )
        ctrl = AirQualitySensor(comp)
        user = mk_user('regular@simo.io', 'Regular')
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(user, self.inst, role)

        GatewayObjectCommand.publish.reset_mock()
        with mock.patch('simo.fleet.controllers.get_current_user', return_value=user):
            with self.assertRaises(ValidationError):
                ctrl.recalibrate()

        GatewayObjectCommand.publish.assert_not_called()

        serializer = ComponentSerializer(
            instance=comp,
            context={
                'request': SimpleNamespace(
                    user=user,
                    path='/',
                    build_absolute_uri=lambda p: p,
                ),
                'instance': self.inst,
            },
        )
        self.assertNotIn('recalibrate', serializer.get_controller_methods(comp))
