from __future__ import annotations

import asyncio
import datetime
from unittest import mock

from django.utils import timezone

from simo.core.middleware import introduce_instance
from simo.core.models import Category, Component, ComponentHistory, Gateway, Zone

from .base import BaseSimoTransactionTestCase, mk_instance, mk_user


class TestMcpCoreToolsDb(BaseSimoTransactionTestCase):
    def test_get_home_overview_returns_compact_weather_main_state_and_component_map(self):
        from simo.core.mcp import get_home_overview
        from simo.generic.controllers import MainState, Weather, SwitchGroup
        from simo.generic.gateways import GenericGatewayHandler
        from simo.core.models import Icon

        inst = mk_instance('inst-overview', 'Overview')
        inst.ai_memory = 'remember this'
        inst.timezone = 'Europe/Vilnius'
        inst.units_of_measure = 'metric'
        inst.save(update_fields=['ai_memory', 'timezone', 'units_of_measure'])

        zone_common = Zone.objects.create(instance=inst, name='Bendra', order=0)
        zone_living = Zone.objects.create(instance=inst, name='Svetainė', order=1)
        cat_lights = Category.objects.create(instance=inst, name='Apšvietimas', all=False, icon=None)
        icon_lamp = Icon.objects.create(slug='lamp-street')
        gw, _ = Gateway.objects.get_or_create(type=GenericGatewayHandler.uid)

        weather = Component.objects.create(
            name='Weather',
            zone=zone_common,
            category=None,
            gateway=gw,
            base_type='weather',
            controller_uid=Weather.uid,
            config={'is_main': True},
            meta={},
            value={
                'main': {'temp': 17.3, 'feels_like': 16.9},
                'wind': {'speed': 3.8},
                'weather': [{'description': 'broken clouds'}],
            },
        )
        main_state = Component.objects.create(
            name='Režimas',
            zone=zone_common,
            category=None,
            gateway=gw,
            base_type='state-select',
            controller_uid=MainState.uid,
            config={
                'is_main': True,
                'states': [{'slug': 'day'}, {'slug': 'night'}],
            },
            meta={},
            value='day',
        )
        lamp = Component.objects.create(
            name='Virtuvės lempa',
            icon=icon_lamp,
            zone=zone_living,
            category=cat_lights,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        introduce_instance(inst)
        fixed_now = timezone.make_aware(datetime.datetime(2025, 1, 2, 3, 4, 5))
        with mock.patch('simo.core.mcp.timezone.now', return_value=fixed_now):
            out = asyncio.run(get_home_overview.fn())

        self.assertEqual(out['ai_memory'], 'remember this')
        self.assertEqual(out['timezone'], 'Europe/Vilnius')
        self.assertEqual(out['component_map_item_format'], '#component_id|icon_slug|component_name')
        self.assertEqual(out['weather']['component_id'], weather.id)
        self.assertEqual(out['weather']['summary'], 'broken clouds')
        self.assertEqual(out['main_house_state']['id'], main_state.id)
        zones = {item['id']: item for item in out['zones']}
        self.assertEqual(
            zones[zone_common.id]['components']['weather'],
            [f'#{weather.id}||Weather'],
        )
        self.assertEqual(
            zones[zone_common.id]['components']['state-select'],
            [f'#{main_state.id}||Režimas'],
        )
        self.assertEqual(
            zones[zone_living.id]['components']['switch'],
            [f'#{lamp.id}|lamp-street|Virtuvės lempa'],
        )

    def test_query_components_returns_actionable_contracts(self):
        from simo.core.mcp import query_components
        from simo.generic.controllers import DimmableLightsGroup, MainState
        from simo.generic.gateways import GenericGatewayHandler

        inst = mk_instance('inst-query', 'Query')
        zone_common = Zone.objects.create(instance=inst, name='Bendra', order=0)
        zone_living = Zone.objects.create(instance=inst, name='Svetainė', order=1)
        cat_lights = Category.objects.create(instance=inst, name='Apšvietimas', all=False, icon=None)
        gw, _ = Gateway.objects.get_or_create(type=GenericGatewayHandler.uid)

        state = Component.objects.create(
            name='Režimas',
            zone=zone_common,
            category=None,
            gateway=gw,
            base_type='state-select',
            controller_uid=MainState.uid,
            config={
                'is_main': True,
                'states': [{'slug': 'day'}, {'slug': 'night'}, {'slug': 'away'}],
            },
            meta={},
            value='day',
        )
        dimmer = Component.objects.create(
            name='Pritemdoma lempa',
            zone=zone_living,
            category=cat_lights,
            gateway=gw,
            base_type='dimmer',
            controller_uid=DimmableLightsGroup.uid,
            config={'min': 10.0, 'max': 90.0, 'inverse': False},
            meta={},
            value=20,
            value_units='%',
            alive=True,
        )

        introduce_instance(inst)
        out = asyncio.run(
            query_components.fn(
                zone_ids=[zone_common.id, zone_living.id],
                base_types=['state-select', 'dimmer'],
                category_names=['Apšvietimas'],
                alive=True,
            )
        )

        self.assertEqual(out['component_count'], 1)
        self.assertEqual(out['components'][0]['id'], dimmer.id)
        send_action = next(
            action for action in out['components'][0]['actions']
            if action['method_name'] == 'send'
        )
        self.assertEqual(send_action['args'][0]['min'], 10.0)
        self.assertEqual(send_action['args'][0]['max'], 90.0)

        out2 = asyncio.run(
            query_components.fn(
                zone_ids=[zone_common.id],
                base_types=['state-select'],
            )
        )
        self.assertEqual(out2['component_count'], 1)
        self.assertEqual(out2['components'][0]['id'], state.id)
        state_send = next(
            action for action in out2['components'][0]['actions']
            if action['method_name'] == 'send'
        )
        self.assertEqual(
            state_send['args'][0]['allowed_values'],
            ['day', 'night', 'away'],
        )

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
