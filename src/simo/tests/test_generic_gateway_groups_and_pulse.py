import time
from unittest import mock

from rest_framework.test import APIClient

from simo.core.events import GatewayObjectCommand
from simo.core.models import Component, Gateway, Zone
from simo.fleet.controllers import Blinds, Button
from simo.fleet.gateways import FleetGatewayHandler
from simo.generic.controllers import BlindsGroup
from simo.generic.gateways import GenericGatewayHandler

from .base import BaseSimoTestCase, mk_instance, mk_instance_user, mk_role, mk_user


class BlindsGroupTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.instance = mk_instance('blind-home', 'Home')
        zone = Zone.objects.create(instance=self.instance, name='Room', order=0)
        owner = mk_user('owner@example.com', 'Owner')
        mk_instance_user(owner, self.instance, mk_role(self.instance, is_owner=True))
        self.api = APIClient()
        self.api.force_authenticate(user=type(owner).objects.get(pk=owner.pk))
        self.components_url = f'/api/{self.instance.slug}/core/components/'
        self.generic, _ = Gateway.objects.get_or_create(type=GenericGatewayHandler.uid)
        fleet, _ = Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        self.first = Component.objects.create(
            name='First', zone=zone, gateway=fleet, controller_uid=Blinds.uid,
            base_type='blinds', config={'slats_angle_duration': 2, 'open_direction': 'up'},
        )
        self.first.controller.set({'target': 40, 'position': 40, 'angle': 120})
        self.first.refresh_from_db()
        self.second = Component.objects.create(
            name='Second', zone=zone, gateway=fleet, controller_uid=Blinds.uid,
            base_type='blinds', config={'slats_angle_duration': 3, 'open_direction': 'down'},
        )
        self.second.controller.set({'target': 20, 'position': 20, 'angle': 30})
        self.second.refresh_from_db()
        response = self.api.post(self.components_url, {
            'name': 'Blinds group', 'zone': zone.pk,
            'reference_blind': self.first.pk, 'additional_blinds': [self.second.pk],
        }, format='json', HTTP_CONTROLLER=BlindsGroup.uid)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['app_widget']['type'], 'slides')
        self.assertEqual(response.data['value'], self.first.value)
        self.assertEqual(response.data['additional_blinds'], [self.second.pk])
        self.assertEqual(response.data['config']['slats_angle_duration'], 2)
        self.group = Component.all_objects.get(pk=response.data['id'])
        self.group_url = f'{self.components_url}{self.group.pk}/'
        self.api.force_authenticate(user=type(owner).objects.get(pk=owner.pk))

    def _commands(self):
        return [
            (call.args[0].data['obj_pk'], call.args[0].data['set_val'])
            for call in GatewayObjectCommand.publish.call_args_list
        ]

    def test_owner_can_change_membership_and_first_blind(self):
        response = self.api.options(self.group_url)
        self.assertEqual(response.status_code, 200, response.data)
        fields = response.data['actions']['PUT']
        self.assertIn('reference_blind', fields)
        self.assertIn('additional_blinds', fields)

        response = self.api.patch(self.group_url, {
            'reference_blind': self.second.pk, 'additional_blinds': [],
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        response = self.api.get(self.group_url)
        self.assertEqual(response.data['reference_blind'], self.second.pk)
        self.assertEqual(response.data['additional_blinds'], [])
        self.assertEqual(response.data['value'], self.second.value)
        self.assertEqual(response.data['config']['open_direction'], 'down')

    def test_slider_sends_both_values_and_group_mirrors_only_first_blind(self):
        GatewayObjectCommand.publish.reset_mock()
        target = {'target': 70, 'angle': 55}
        response = self.api.post(f'{self.group_url}controller/', {'send': [target]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._commands(), [(self.first.pk, target), (self.second.pk, target)])

        reported = {**target, 'position': 67}
        with self.captureOnCommitCallbacks(execute=True):
            self.second.controller.set(reported)
        self.group.refresh_from_db()
        self.assertEqual(self.group.value, self.first.value)

        with self.captureOnCommitCallbacks(execute=True):
            self.first.controller.set(reported)
        self.group.refresh_from_db()
        self.assertEqual(self.group.value, reported)

    def test_group_becomes_unavailable_when_first_blind_is_deleted(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.first.delete()
        self.group.refresh_from_db()
        self.assertFalse(self.group.alive)

    def test_physical_button_binding_can_set_group_angle(self):
        button = Component.objects.create(
            name='Angle', zone=self.first.zone, gateway=self.first.gateway,
            controller_uid=Button.uid, base_type='button',
        )
        self.api.force_authenticate(user=mk_user('installer@example.com', 'Installer', is_master=True))
        bindings = [{
            'button': button.pk, 'event': 'click', 'action': 'open',
        }, {
            'button': button.pk, 'event': 'hold', 'action': 'set_angle', 'angle': 90,
        }, {
            'button': button.pk, 'event': 'double-click', 'action': 'stop',
        }]
        response = self.api.patch(self.group_url, {'controls': bindings}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        handler = self.generic.handler
        with mock.patch.object(Component, 'on_change', autospec=True) as on_change:
            handler.watch_groups()
            handler.watch_groups()
        on_change.assert_called_once()

        GatewayObjectCommand.publish.reset_mock()
        button.value = 'hold'
        handler.watch_group_button(button)
        target = {'target': 40, 'angle': 90}
        self.assertEqual(self._commands(), [(self.first.pk, target), (self.second.pk, target)])

        GatewayObjectCommand.publish.reset_mock()
        button.value = 'click'
        handler.watch_group_button(button)
        target = {'target': 100, 'angle': 120}
        self.assertEqual(self._commands(), [(self.first.pk, target), (self.second.pk, target)])

        GatewayObjectCommand.publish.reset_mock()
        button.value = 'double-click'
        handler.watch_group_button(button)
        self.assertEqual(self._commands(), [
            (self.first.pk, {'target': -1, 'angle': 120}),
            (self.second.pk, {'target': -1, 'angle': 30}),
        ])


class FakeMqttClient:
    def username_pw_set(self, *_args, **_kwargs):
        return None

    def reconnect_delay_set(self, **_kwargs):
        return None


class GenericGatewayGroupsAndPulseTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.generic.gateways import GenericGatewayHandler

        self.gw, _ = Gateway.objects.get_or_create(type=GenericGatewayHandler.uid)

    def _mk_handler(self):
        from simo.generic.gateways import GenericGatewayHandler

        with mock.patch('simo.core.gateways.mqtt.Client', autospec=True, return_value=FakeMqttClient()):
            handler = GenericGatewayHandler(self.gw)
        handler.logger = mock.Mock()
        return handler

    def test_watch_groups_builds_button_to_groups_map_and_subscribes(self):
        from simo.generic.controllers import SwitchGroup

        handler = self._mk_handler()

        btn = Component.objects.create(
            name='B',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='button',
            controller_uid='x',
            config={},
            meta={},
            value='up',
        )
        group = Component.objects.create(
            name='G',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={'controls': [{'button': btn.id}]},
            meta={},
            value=False,
        )

        with mock.patch('simo.core.events.OnChangeMixin.on_change', autospec=True) as on_change:
            handler.watch_groups()

        self.assertEqual(handler.group_buttons.get(btn.id), {group.id})
        on_change.assert_called_once()

    def test_watch_group_button_click_calls_toggle(self):
        from simo.generic.controllers import SwitchGroup

        handler = self._mk_handler()

        btn = Component.objects.create(
            name='B',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='button',
            controller_uid='x',
            config={},
            meta={},
            value='click',
        )
        group = Component.objects.create(
            name='G',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={'controls': [{'button': btn.id}]},
            meta={},
            value=False,
        )
        handler.group_buttons[btn.id] = {group.id}

        with mock.patch('simo.core.controllers.Switch.toggle', autospec=True) as toggle:
            handler.watch_group_button(btn)
        toggle.assert_called_once()

    def test_watch_group_button_double_click_sends_max(self):
        from simo.generic.controllers import SwitchGroup

        handler = self._mk_handler()

        btn = Component.objects.create(
            name='B',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='button',
            controller_uid='x',
            config={},
            meta={},
            value='double-click',
        )
        group = Component.objects.create(
            name='G',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={'controls': [{'button': btn.id}], 'max': 42},
            meta={},
            value=False,
        )
        handler.group_buttons[btn.id] = {group.id}

        with mock.patch('simo.core.controllers.Switch.send', autospec=True) as send:
            handler.watch_group_button(btn)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1], 42)

    def test_watch_group_button_momentary_down_calls_fade_down(self):
        from simo.generic.controllers import DimmableLightsGroup

        handler = self._mk_handler()

        btn = Component.objects.create(
            name='B',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='button',
            controller_uid='x',
            config={},
            meta={},
            value='down',
        )
        group = Component.objects.create(
            name='DG',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='dimmer',
            controller_uid=DimmableLightsGroup.uid,
            config={'controls': [{'button': btn.id}]},
            meta={},
            value=0,
        )
        handler.group_buttons[btn.id] = {group.id}

        with mock.patch('simo.core.controllers.Dimmer.fade_down', autospec=True, return_value=None) as fade_down:
            handler.watch_group_button(btn)
        fade_down.assert_called_once()

    def test_start_pulse_sends_true_and_tracks_switch(self):
        from simo.generic.controllers import SwitchGroup

        handler = self._mk_handler()
        comp = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        pulse = {'frame': 2.0, 'duty': 0.25}
        with mock.patch.object(comp, 'send', autospec=True) as send:
            handler.start_pulse(comp, pulse)

        send.assert_called_once()
        self.assertIn(comp.id, handler.pulsing_switches)
        self.assertEqual(handler.pulsing_switches[comp.id]['pulse'], pulse)
        self.assertTrue(handler.pulsing_switches[comp.id]['value'])
        self.assertLessEqual(handler.pulsing_switches[comp.id]['last_toggle'], time.time())

    def test_start_pulse_updates_existing_switch_without_restart(self):
        from simo.generic.controllers import SwitchGroup

        handler = self._mk_handler()
        comp = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        handler.pulsing_switches[comp.id] = {
            'comp': comp,
            'last_toggle': 123.0,
            'value': False,
            'pulse': {'frame': 300, 'duty': 0.4},
        }
        pulse = {'frame': 300, 'duty': 0.45}

        with mock.patch.object(comp, 'send', autospec=True) as send:
            handler.start_pulse(comp, pulse)

        send.assert_not_called()
        self.assertEqual(handler.pulsing_switches[comp.id]['pulse'], pulse)
        self.assertEqual(handler.pulsing_switches[comp.id]['last_toggle'], 123.0)
        self.assertFalse(handler.pulsing_switches[comp.id]['value'])
