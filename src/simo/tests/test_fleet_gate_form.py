from types import SimpleNamespace

from simo.core.models import Component, Gateway, Zone
from simo.core.middleware import introduce_instance
from simo.fleet.controllers import Blinds, Gate
from simo.fleet.forms import BlindsConfigForm, GateConfigForm
from simo.fleet.gateways import FleetGatewayHandler
from simo.fleet.models import Colonel

from .base import BaseSimoTestCase, mk_instance, mk_instance_user, mk_role, mk_user


class GateConfigFormTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.inst.location = '0,0'
        self.inst.save(update_fields=['location'])
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        self.fleet_gw = Gateway.objects.get(type=FleetGatewayHandler.uid)
        self.colonel = Colonel.objects.create(
            instance=self.inst, uid='c-1', type='sentinel', name='C1'
        )
        output_pins = list(self.colonel.pins.filter(output=True)[:2])
        self.open_pin = output_pins[0] if output_pins else None
        self.close_pin = output_pins[1] if len(output_pins) > 1 else None
        excluded_pin_ids = [pin.id for pin in output_pins]
        self.sensor_pin = self.colonel.pins.filter(input=True).exclude(
            id__in=excluded_pin_ids
        ).first()
        self.assertIsNotNone(self.open_pin)
        self.assertIsNotNone(self.close_pin)
        self.assertIsNotNone(self.sensor_pin)

    def _data(self, **overrides):
        data = {
            'name': 'Gate 1',
            'zone': self.zone.id,
            'colonel': self.colonel.id,
            'open_pin': self.open_pin.id,
            'open_action': 'HIGH',
            'close_action': 'HIGH',
            'control_method': 'pulse',
            'control_layout': 'directional',
            'closed_value': 'LOW',
            'open_duration': '30',
            'auto_open_distance': '',
            'location': '0,0',
        }
        data.update(overrides)
        return data

    def _form(self, auto_open_distance):
        return GateConfigForm(
            controller_uid=Gate.uid,
            data=self._data(auto_open_distance=auto_open_distance),
        )

    def test_rejects_auto_open_distance_without_units(self):
        form = self._form('200')

        self.assertFalse(form.is_valid())
        self.assertIn('auto_open_distance', form.errors)
        self.assertIn(
            'Please specify a numerical value followed by a valid unit of measure',
            form.errors['auto_open_distance'][0],
        )

    def test_accepts_auto_open_distance_with_units(self):
        form = self._form('200 m')

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['auto_open_distance'], '200 m')

    def test_partial_form_without_location_does_not_crash(self):
        introduce_instance(self.inst)
        gate = Component.objects.create(
            name='Gate base',
            zone=self.zone,
            category=None,
            gateway=self.fleet_gw,
            base_type='gate',
            controller_uid=Gate.uid,
            config={
                'colonel': self.colonel.id,
                'open_pin_no': self.open_pin.no,
                'open_action': 'HIGH',
                'close_action': 'HIGH',
                'control_method': 'pulse',
                'closed_value': 'LOW',
                'open_duration': 30,
                'auto_open_distance': '100 m',
                'location': '0,0',
            },
            meta={},
            value=0,
        )

        form = GateConfigForm(
            instance=gate,
            data={
                'name': 'Gate 1',
                'zone': self.zone.id,
                'auto_open_distance': '200 m',
            },
        )

        self.assertNotIn('location', form.fields)

    def test_save_claims_gate_pins_on_colonel(self):
        form = GateConfigForm(
            controller_uid=Gate.uid,
            data=self._data(
                close_pin=self.close_pin.id,
                sensor_pin=self.sensor_pin.id,
            ),
        )

        self.assertTrue(form.is_valid(), form.errors)
        component = form.save()

        for pin in (self.open_pin, self.close_pin, self.sensor_pin):
            pin.refresh_from_db()
            self.assertEqual(pin.occupied_by_id, component.id)

    def test_save_persists_parallel_control_layout(self):
        form = GateConfigForm(
            controller_uid=Gate.uid,
            data=self._data(control_layout='parallel'),
        )

        self.assertTrue(form.is_valid(), form.errors)
        component = form.save()

        self.assertEqual(component.config['control_layout'], 'parallel')

    def test_regular_user_can_edit_auto_open_distance_only(self):
        user = mk_user('regular@simo.io', 'Regular User')
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(user, self.inst, role)
        component = Component.objects.create(
            name='Gate 1',
            zone=self.zone,
            category=None,
            gateway=self.fleet_gw,
            base_type='gate',
            controller_uid=Gate.uid,
            config={
                'colonel': self.colonel.id,
                'auto_open_distance': '100 m',
            },
            meta={},
            value='closed',
        )
        request = SimpleNamespace(user=user, path='/', build_absolute_uri=lambda p: p)

        from simo.core.serializers import ComponentSerializer

        serializer = ComponentSerializer(
            instance=component,
            context={'request': request, 'instance': self.inst},
        )
        form = serializer.get_form(instance=component)

        self.assertIn('auto_open_distance', form.fields)
        self.assertNotIn('open_pin', form.fields)

    def test_edit_form_save_repairs_missing_gate_pin_occupancy(self):
        form = GateConfigForm(
            controller_uid=Gate.uid,
            data=self._data(),
        )
        self.assertTrue(form.is_valid(), form.errors)
        component = form.save()

        self.open_pin.refresh_from_db()
        self.assertEqual(self.open_pin.occupied_by_id, component.id)

        self.colonel.pins.filter(id=self.open_pin.id).update(
            occupied_by_content_type=None,
            occupied_by_id=None,
        )
        self.open_pin.refresh_from_db()
        self.assertIsNone(self.open_pin.occupied_by_id)

        form = GateConfigForm(
            instance=component,
            data=self._data(name='Gate 1 renamed'),
        )

        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.open_pin.refresh_from_db()
        self.assertEqual(self.open_pin.occupied_by_id, component.id)


class BlindsConfigFormTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        self.colonel = Colonel.objects.create(
            instance=self.inst, uid='c-2', type='sentinel', name='C2'
        )
        output_pins = list(self.colonel.pins.filter(output=True)[:2])
        self.open_pin, self.close_pin = output_pins

    def test_save_persists_parallel_control_layout(self):
        form = BlindsConfigForm(
            controller_uid=Blinds.uid,
            data={
                'name': 'Blind 1',
                'zone': self.zone.id,
                'colonel': self.colonel.id,
                'open_pin': self.open_pin.id,
                'open_action': 'HIGH',
                'close_pin': self.close_pin.id,
                'close_action': 'HIGH',
                'open_direction': 'up',
                'open_duration': '30',
                'close_duration': '30',
                'control_type': 'hold',
                'control_mode': 'click',
                'control_layout': 'parallel',
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        component = form.save()

        self.assertEqual(component.config['control_layout'], 'parallel')
