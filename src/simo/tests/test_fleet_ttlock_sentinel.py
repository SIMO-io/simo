from simo.core.models import Gateway, Zone
from simo.fleet.controllers import TTLock
from simo.fleet.forms import TTLockConfigForm
from simo.fleet.gateways import FleetGatewayHandler
from simo.fleet.models import Colonel

from .base import BaseSimoTestCase, mk_instance


class TTLockSentinelConfigFormTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        self.sentinel = Colonel.objects.create(
            instance=self.inst, uid='s-1', type='sentinel', name='S1'
        )

    def _form_data(self, name='Front Door'):
        return {
            'name': name,
            'zone': self.zone.id,
            'colonel': self.sentinel.id,
            'auto_lock': 5,
        }

    def test_form_explicitly_supports_sentinel_as_ttlock_host(self):
        form = TTLockConfigForm(
            controller_uid=TTLock.uid,
            data=self._form_data(),
        )

        self.assertEqual(form.fields['colonel'].label, 'Sentinel / Colonel')
        self.assertIn(
            'manage this TTLock over BLE',
            form.fields['colonel'].help_text,
        )
        self.assertTrue(form.is_valid(), form.errors)

        component = form.save()

        self.assertEqual(component.config['colonel'], self.sentinel.id)
        self.assertEqual(component.config['auto_lock'], 5)

    def test_single_ttlock_limit_uses_generic_device_wording(self):
        first_form = TTLockConfigForm(
            controller_uid=TTLock.uid,
            data=self._form_data(name='Lock 1'),
        )
        self.assertTrue(first_form.is_valid(), first_form.errors)
        first_form.save()

        second_form = TTLockConfigForm(
            controller_uid=TTLock.uid,
            data=self._form_data(name='Lock 2'),
        )

        self.assertFalse(second_form.is_valid())
        self.assertIn(
            'Single Fleet device can support a single TTLock only.',
            second_form.non_field_errors()[0],
        )
