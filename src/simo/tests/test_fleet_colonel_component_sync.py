from simo.core.models import Gateway, Zone
from simo.core.events import GatewayObjectCommand
from simo.fleet.controllers import DALIBusDimmer, VoiceAssistant
from simo.fleet.forms import DaliBusDimmerForm, VoiceAssistantConfigForm
from simo.fleet.gateways import FleetGatewayHandler
from simo.fleet.models import Colonel, Interface

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

    def test_component_save_defers_colonel_config_push_until_commit(self):
        comp = self._mk_va('VA4')

        GatewayObjectCommand.publish.reset_mock()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            comp.config['colonel'] = self.s1.id
            comp.save(update_fields=['config'])
            GatewayObjectCommand.publish.assert_not_called()

        self.assertTrue(callbacks)
        for callback in callbacks:
            callback()

        self.assertTrue(GatewayObjectCommand.publish.called)
        self.assertTrue(any(
            call.args[0].data.get('command') == 'update_config'
            for call in GatewayObjectCommand.publish.call_args_list
        ))

    def test_dali_bus_dimmer_manual_add_finalizes_on_colonel(self):
        colonel = Colonel.objects.create(
            instance=self.inst, uid='dali-1', name='D1'
        )
        interface = Interface.objects.create(
            colonel=colonel, no=1, type='dali'
        )

        form = DaliBusDimmerForm(
            controller_uid=DALIBusDimmer.uid,
            data={
                'name': 'Bus Dimmer',
                'zone': self.zone.id,
                'colonel': colonel.id,
                'interface': interface.id,
                'on_value': 100,
            },
        )
        self.assertTrue(form.is_valid(), form.errors)

        GatewayObjectCommand.publish.reset_mock()
        comp = form.save()

        self.assertEqual(comp.controller_uid, DALIBusDimmer.uid)
        self.assertEqual(comp.base_type, 'dimmer')
        self.assertEqual(comp.config['colonel'], colonel.id)
        self.assertEqual(comp.config['interface'], interface.id)
        self.assertEqual(comp.config['dali_interface'], interface.no)

        finalize_calls = [
            call.args[0].data
            for call in GatewayObjectCommand.publish.call_args_list
            if call.args[0].data.get('command') == 'finalize'
        ]
        self.assertTrue(finalize_calls)
        finalize = finalize_calls[-1]
        self.assertEqual(finalize['data']['permanent_id'], comp.id)
        self.assertEqual(
            finalize['data']['comp_config']['type'],
            'DALIBusDimmer'
        )
        self.assertEqual(
            finalize['data']['comp_config']['family'],
            'dali'
        )
        self.assertEqual(
            finalize['data']['comp_config']['config']['dali_interface'],
            1
        )
