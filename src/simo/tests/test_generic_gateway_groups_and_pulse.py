import time
from unittest import mock

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


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
        with mock.patch('simo.core.controllers.Switch.send', autospec=True) as send:
            handler.start_pulse(comp, pulse)

        send.assert_called_once()
        self.assertIn(comp.id, handler.pulsing_switches)
        self.assertEqual(handler.pulsing_switches[comp.id]['pulse'], pulse)
        self.assertTrue(handler.pulsing_switches[comp.id]['value'])
        self.assertLessEqual(handler.pulsing_switches[comp.id]['last_toggle'], time.time())

