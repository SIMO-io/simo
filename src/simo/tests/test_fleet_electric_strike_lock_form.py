from simo.core.models import Gateway, Zone
from simo.fleet.controllers import ElectricStrikeLock
from simo.fleet.forms import ElectricStrikeLockConfigForm
from simo.fleet.gateways import FleetGatewayHandler
from simo.fleet.models import Colonel

from .base import BaseSimoTestCase, mk_instance


class ElectricStrikeLockConfigFormTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        self.colonel = Colonel.objects.create(
            instance=self.inst, uid='c-1', type='game-changer-mini', name='C1'
        )
        self.open_pin = self.colonel.pins.filter(output=True).first()
        self.assertIsNotNone(self.open_pin)
        self.status_pin = self.colonel.pins.filter(input=True).exclude(
            id=self.open_pin.id
        ).first()
        self.assertIsNotNone(self.status_pin)

    def test_saves_pin_numbers_and_uses_locked_default_value(self):
        form = ElectricStrikeLockConfigForm(
            controller_uid=ElectricStrikeLock.uid,
            data={
                'name': 'Front Door',
                'zone': self.zone.id,
                'colonel': self.colonel.id,
                'open_pin': self.open_pin.id,
                'open_action': 'HIGH',
                'control_method': 'pulse',
                'status_pin': self.status_pin.id,
                'unlocked_value': 'HIGH',
                'auto_lock': '0',
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        component = form.save()

        self.assertEqual(component.value, 'locked')
        self.assertEqual(component.config['open_pin_no'], self.open_pin.no)
        self.assertEqual(component.config['status_pin_no'], self.status_pin.no)

    def test_autolock_choices_match_supported_hold_durations(self):
        form = ElectricStrikeLockConfigForm(controller_uid=ElectricStrikeLock.uid)

        self.assertEqual(
            [value for value, _label in form.fields['auto_lock'].choices],
            [0, 30, 60, 300, 900, 1800, 3600, 7200, 14400, 21600,
             28800, 43200, 64800, 86400],
        )
