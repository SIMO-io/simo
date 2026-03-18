from simo.core.models import Gateway, Zone
from simo.fleet.controllers import VoiceAssistant
from simo.fleet.forms import VoiceAssistantConfigForm
from simo.fleet.gateways import FleetGatewayHandler
from simo.fleet.models import Colonel

from .base import BaseSimoTestCase, mk_instance


class FleetColonelComponentSyncTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        self.s1 = Colonel.objects.create(
            instance=self.inst, uid='s-1', type='sentinel', name='S1'
        )
        self.s2 = Colonel.objects.create(
            instance=self.inst, uid='s-2', type='sentinel', name='S2'
        )

    def _mk_va(self, name: str):
        form = VoiceAssistantConfigForm(
            controller_uid=VoiceAssistant.uid,
            data={
                'name': name,
                'zone': self.zone.id,
                'assistant': 'alora',
                'language': 'en',
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    def test_default_config_not_shared_between_components(self):
        comp1 = self._mk_va('VA1')
        comp1.config['colonel'] = self.s1.id
        comp1.save(update_fields=['config'])

        comp2 = self._mk_va('VA2')
        self.assertIsNone(comp2.config.get('colonel'))
        self.assertFalse(self.s1.components.filter(id=comp2.id).exists())

        comp2.config['colonel'] = self.s2.id
        comp2.save(update_fields=['config'])
        self.assertTrue(self.s2.components.filter(id=comp2.id).exists())
        self.assertFalse(self.s1.components.filter(id=comp2.id).exists())

    def test_component_reassignment_removes_stale_colonel_link(self):
        comp = self._mk_va('VA3')
        comp.config['colonel'] = self.s1.id
        comp.save(update_fields=['config'])
        self.assertTrue(self.s1.components.filter(id=comp.id).exists())

        comp.config['colonel'] = self.s2.id
        comp.save(update_fields=['config'])
        self.assertTrue(self.s2.components.filter(id=comp.id).exists())
        self.assertFalse(self.s1.components.filter(id=comp.id).exists())
