from simo.core.models import Component, Gateway, Zone
from simo.core.middleware import introduce_instance
from simo.fleet.controllers import Gate
from simo.fleet.forms import GateConfigForm
from simo.fleet.gateways import FleetGatewayHandler
from simo.fleet.models import Colonel

from .base import BaseSimoTestCase, mk_instance


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
        self.open_pin = self.colonel.pins.filter(output=True).first()
        self.assertIsNotNone(self.open_pin)

    def _form(self, auto_open_distance):
        return GateConfigForm(
            controller_uid=Gate.uid,
            data={
                'name': 'Gate 1',
                'zone': self.zone.id,
                'colonel': self.colonel.id,
                'open_pin': self.open_pin.id,
                'open_action': 'HIGH',
                'close_action': 'HIGH',
                'control_method': 'pulse',
                'closed_value': 'LOW',
                'open_duration': '30',
                'auto_open_distance': auto_open_distance,
                'location': '0,0',
            },
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
