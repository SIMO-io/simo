from __future__ import annotations

import asyncio
import datetime
from unittest import mock

from django.utils import timezone

from simo.core.middleware import introduce_instance
from simo.core.models import Category, Component, ComponentHistory, Gateway, Zone

from .base import BaseSimoTransactionTestCase, mk_instance, mk_user


class TestMcpCoreToolsDb(BaseSimoTransactionTestCase):
    def test_get_state_is_instance_scoped(self):
        from simo.core.mcp import get_state
        from simo.generic.controllers import SwitchGroup

        inst_a = mk_instance('inst-a', 'A')
        inst_b = mk_instance('inst-b', 'B')
        inst_a.ai_memory = 'mem-a'
        inst_a.save(update_fields=['ai_memory'])

        zone_a = Zone.objects.create(instance=inst_a, name='ZA', order=0)
        Zone.objects.create(instance=inst_b, name='ZB', order=0)

        cat_a = Category.objects.create(instance=inst_a, name='CA', all=False, icon=None)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp_a = Component.objects.create(
            name='Lamp',
            zone=zone_a,
            category=cat_a,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        introduce_instance(inst_a)
        fixed_now = timezone.make_aware(datetime.datetime(2025, 1, 1, 0, 0, 0))
        with mock.patch('simo.core.mcp.timezone.now', return_value=fixed_now):
            out = asyncio.run(get_state.fn())

        self.assertEqual(out['ai_memory'], 'mem-a')
        self.assertEqual(out['unix_timestamp'], int(fixed_now.timestamp()))
        zones = out['zones']
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]['id'], zone_a.id)
        comp_ids = [c['id'] for c in zones[0]['components']]
        self.assertEqual(comp_ids, [comp_a.id])

    def test_get_component_returns_data_for_current_instance(self):
        from simo.core.mcp import get_component
        from simo.generic.controllers import SwitchGroup

        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        cat = Category.objects.create(instance=inst, name='C', all=False, icon=None)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp = Component.objects.create(
            name='Lamp',
            zone=zone,
            category=cat,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        introduce_instance(inst)
        out = asyncio.run(get_component.fn(str(comp.id)))
        self.assertEqual(out['id'], comp.id)
        self.assertEqual(out['name'], 'Lamp')

    def test_get_component_returns_empty_for_other_instance(self):
        from simo.core.mcp import get_component
        from simo.generic.controllers import SwitchGroup

        inst_a = mk_instance('inst-a', 'A')
        inst_b = mk_instance('inst-b', 'B')
        zone_b = Zone.objects.create(instance=inst_b, name='ZB', order=0)
        cat_b = Category.objects.create(instance=inst_b, name='CB', all=False, icon=None)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp_b = Component.objects.create(
            name='Secret',
            zone=zone_b,
            category=cat_b,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        introduce_instance(inst_a)
        out = asyncio.run(get_component.fn(str(comp_b.id)))
        self.assertEqual(out, {})

    def test_get_component_value_change_history_filters_by_ids_and_formats_time(self):
        from simo.core.mcp import get_component_value_change_history
        from simo.generic.controllers import SwitchGroup

        inst = mk_instance('inst-a', 'A')
        inst.timezone = 'UTC'
        inst.save(update_fields=['timezone'])
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        cat = Category.objects.create(instance=inst, name='C', all=False, icon=None)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        comp = Component.objects.create(
            name='Lamp',
            zone=zone,
            category=cat,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        user = mk_user('u@example.com', 'U')

        ts = timezone.make_aware(datetime.datetime(2025, 1, 1, 0, 0, 0))
        with mock.patch('django.utils.timezone.now', return_value=ts):
            ComponentHistory.objects.create(
                component=comp,
                type='value',
                value=True,
                user=user,
                alive=True,
            )

        introduce_instance(inst)
        out = asyncio.run(
            get_component_value_change_history.fn(
                0,
                int((ts + datetime.timedelta(days=1)).timestamp()),
                str(comp.id),
            )
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['component_id'], comp.id)
        self.assertEqual(out[0]['user'], 'U')
        self.assertEqual(out[0]['datetime'], '2025-01-01 00:00:00')

    def test_get_component_value_change_history_invalid_ids_returns_empty(self):
        from simo.core.mcp import get_component_value_change_history

        inst = mk_instance('inst-a', 'A')
        introduce_instance(inst)
        out = asyncio.run(get_component_value_change_history.fn(0, 10, 'nope'))
        self.assertEqual(out, [])
