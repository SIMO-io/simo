from __future__ import annotations

from simo.core.models import Category, Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class TestComponentFormsSecurity(BaseSimoTestCase):
    def test_switch_form_rejects_cross_instance_slaves(self):
        from simo.core.forms import SwitchForm
        from simo.generic.controllers import SwitchGroup

        inst_a = mk_instance('inst-a', 'A')
        inst_b = mk_instance('inst-b', 'B')
        zone_a = Zone.objects.create(instance=inst_a, name='Z', order=0)
        zone_b = Zone.objects.create(instance=inst_b, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        master = Component.objects.create(
            name='Master',
            zone=zone_a,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        slave_other = Component.objects.create(
            name='Other',
            zone=zone_b,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        form = SwitchForm(
            instance=master,
            data={'slaves': [str(slave_other.id)]},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('slaves', form.errors)

    def test_switch_form_rejects_self_as_slave(self):
        from simo.core.forms import SwitchForm
        from simo.generic.controllers import SwitchGroup

        inst_a = mk_instance('inst-a', 'A')
        zone_a = Zone.objects.create(instance=inst_a, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        master = Component.objects.create(
            name='Master',
            zone=zone_a,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        form = SwitchForm(
            instance=master,
            data={'slaves': [str(master.id)]},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('slaves', form.errors)

    def test_component_admin_form_rejects_zone_from_other_instance(self):
        from simo.core.forms import ComponentAdminForm
        from simo.generic.controllers import SwitchGroup

        inst_a = mk_instance('inst-a', 'A')
        inst_b = mk_instance('inst-b', 'B')
        zone_a = Zone.objects.create(instance=inst_a, name='ZA', order=0)
        zone_b = Zone.objects.create(instance=inst_b, name='ZB', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        comp = Component.objects.create(
            name='C',
            zone=zone_a,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        form = ComponentAdminForm(instance=comp, data={'zone': str(zone_b.id)})
        self.assertFalse(form.is_valid())
        self.assertIn('zone', form.errors)

    def test_component_admin_form_rejects_category_from_other_instance(self):
        from simo.core.forms import ComponentAdminForm
        from simo.generic.controllers import SwitchGroup

        inst_a = mk_instance('inst-a', 'A')
        inst_b = mk_instance('inst-b', 'B')
        zone_a = Zone.objects.create(instance=inst_a, name='ZA', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        cat_b = Category.objects.create(instance=inst_b, name='CB', all=False, icon=None)

        comp = Component.objects.create(
            name='C',
            zone=zone_a,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        form = ComponentAdminForm(instance=comp, data={'category': str(cat_b.id)})
        self.assertFalse(form.is_valid())
        self.assertIn('category', form.errors)

    def test_component_admin_form_rejects_generic_all_category(self):
        from simo.core.forms import ComponentAdminForm
        from simo.generic.controllers import SwitchGroup

        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        cat = Category.objects.create(instance=inst, name='All', all=True, icon=None)

        comp = Component.objects.create(
            name='C',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        form = ComponentAdminForm(instance=comp, data={'category': str(cat.id)})
        self.assertFalse(form.is_valid())
        self.assertIn('category', form.errors)

