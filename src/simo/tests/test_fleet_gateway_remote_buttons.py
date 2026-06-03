from unittest import mock

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class FakeMqttClient:
    def username_pw_set(self, *_args, **_kwargs):
        return None

    def reconnect_delay_set(self, **_kwargs):
        return None


class FleetGatewayRemoteButtonTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.fleet.gateways import FleetGatewayHandler

        self.gw, _ = Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)

    def _mk_handler(self):
        from simo.fleet.gateways import FleetGatewayHandler

        with mock.patch(
            'simo.core.gateways.mqtt.Client',
            autospec=True,
            return_value=FakeMqttClient(),
        ):
            handler = FleetGatewayHandler(self.gw)
        handler.logger = mock.Mock()
        return handler

    def _make_button(self, name, colonel, value='down'):
        from simo.fleet.controllers import Button

        return Component.objects.create(
            name=name,
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='button',
            controller_uid=Button.uid,
            config={'colonel': colonel},
            meta={},
            value=value,
        )

    def _make_switch(self, name, colonel, controls):
        from simo.fleet.controllers import Switch

        return Component.objects.create(
            name=name,
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=Switch.uid,
            config={
                'colonel': colonel,
                'inverse': True,
                'output_pin': 1,
                'output_pin_no': 1,
                'controls': controls,
            },
            meta={},
            value=False,
        )

    def _make_electric_strike_lock(self, name, colonel, controls):
        from simo.fleet.controllers import ElectricStrikeLock

        return Component.objects.create(
            name=name,
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='lock',
            controller_uid=ElectricStrikeLock.uid,
            config={
                'colonel': colonel,
                'open_pin_no': 1,
                'status_pin_no': 5,
                'controls': controls,
            },
            meta={},
            value='locked',
        )

    def test_watch_buttons_tracks_all_remote_controls_on_switch(self):
        handler = self._mk_handler()
        button_a = self._make_button('B1', 18)
        button_b = self._make_button('B2', 18)
        button_c = self._make_button('B3', 18)
        switch = self._make_switch(
            'S',
            8,
            [
                {
                    'input': f'button-{button_a.id}',
                    'button': button_a.id,
                    'method': 'momentary',
                    'action_method': 'down',
                },
                {
                    'input': f'button-{button_b.id}',
                    'button': button_b.id,
                    'method': 'momentary',
                    'action_method': 'down',
                },
                {
                    'input': f'button-{button_c.id}',
                    'button': button_c.id,
                    'method': 'momentary',
                    'action_method': 'down',
                },
            ],
        )

        with mock.patch('simo.core.events.OnChangeMixin.on_change', autospec=True) as on_change:
            handler.watch_buttons()

        self.assertEqual(
            handler.remote_button_targets,
            {
                button_a.id: {(switch.id, 0)},
                button_b.id: {(switch.id, 1)},
                button_c.id: {(switch.id, 2)},
            },
        )
        self.assertCountEqual(
            [call.args[0].id for call in on_change.call_args_list],
            [button_a.id, button_b.id, button_c.id],
        )
        self.assertTrue(
            all(call.args[1] == handler.on_remote_button_change for call in on_change.call_args_list)
        )

    def test_watch_buttons_tracks_remote_controls_on_electric_strike_lock(self):
        handler = self._mk_handler()
        button = self._make_button('B1', 18)
        lock = self._make_electric_strike_lock(
            'L',
            8,
            [
                {
                    'input': f'button-{button.id}',
                    'button': button.id,
                    'method': 'momentary',
                    'action_method': 'down',
                },
            ],
        )

        with mock.patch('simo.core.events.OnChangeMixin.on_change', autospec=True):
            handler.watch_buttons()

        self.assertEqual(
            handler.remote_button_targets,
            {button.id: {(lock.id, 0)}},
        )

    def test_on_remote_button_change_routes_third_remote_control(self):
        handler = self._mk_handler()
        button_a = self._make_button('B1', 18)
        button_b = self._make_button('B2', 18)
        button_c = self._make_button('B3', 18, value='down')
        self._make_switch(
            'S',
            8,
            [
                {
                    'input': f'button-{button_a.id}',
                    'button': button_a.id,
                    'method': 'momentary',
                    'action_method': 'down',
                },
                {
                    'input': f'button-{button_b.id}',
                    'button': button_b.id,
                    'method': 'momentary',
                    'action_method': 'down',
                },
                {
                    'input': f'button-{button_c.id}',
                    'button': button_c.id,
                    'method': 'momentary',
                    'action_method': 'down',
                },
            ],
        )

        with mock.patch('simo.core.events.OnChangeMixin.on_change', autospec=True):
            handler.watch_buttons()

        with mock.patch('simo.fleet.controllers.BasicOutputMixin._ctrl', autospec=True) as ctrl:
            handler.on_remote_button_change(button_c)

        ctrl.assert_called_once()
        self.assertEqual(ctrl.call_args.args[1:], (2, 'down', 'momentary'))

    def test_on_remote_button_change_fans_out_shared_remote_button(self):
        handler = self._mk_handler()
        shared = self._make_button('Shared', 18, value='down')
        other = self._make_button('Other', 18, value='down')
        self._make_switch(
            'S1',
            8,
            [{'button': shared.id, 'method': 'momentary'}],
        )
        self._make_switch(
            'S2',
            9,
            [
                {
                    'input': f'button-{other.id}',
                    'button': other.id,
                    'method': 'momentary',
                },
                {
                    'input': f'button-{shared.id}',
                    'button': shared.id,
                    'method': 'momentary',
                },
            ],
        )

        with mock.patch('simo.core.events.OnChangeMixin.on_change', autospec=True):
            handler.watch_buttons()

        with mock.patch('simo.fleet.controllers.BasicOutputMixin._ctrl', autospec=True) as ctrl:
            handler.on_remote_button_change(shared)

        self.assertEqual(ctrl.call_count, 2)
        self.assertCountEqual(
            [call.args[1:] for call in ctrl.call_args_list],
            [(0, 'down', 'momentary'), (1, 'down', 'momentary')],
        )

    def test_on_remote_button_change_is_ignored_when_service_suspended(self):
        handler = self._mk_handler()
        shared = self._make_button('Shared', 18, value='down')
        self._make_switch(
            'S1',
            8,
            [{'button': shared.id, 'method': 'momentary'}],
        )

        with mock.patch('simo.core.events.OnChangeMixin.on_change', autospec=True):
            handler.watch_buttons()

        with (
            mock.patch('simo.core.service_suspension.dynamic_settings', {'core__service_suspended': True}),
            mock.patch('simo.fleet.controllers.BasicOutputMixin._ctrl', autospec=True) as ctrl,
        ):
            handler.on_remote_button_change(shared)

        ctrl.assert_not_called()

    def test_watch_buttons_unbinds_removed_remote_buttons(self):
        handler = self._mk_handler()
        button = self._make_button('B', 18)
        switch = self._make_switch(
            'S',
            8,
            [{'input': f'button-{button.id}', 'button': button.id, 'method': 'momentary'}],
        )

        with mock.patch('simo.core.events.OnChangeMixin.on_change', autospec=True) as on_change:
            handler.watch_buttons()
            switch.config['controls'] = []
            switch.save(update_fields=['config'])
            handler.watch_buttons()

        self.assertEqual(handler.remote_button_targets, {})
        self.assertFalse(handler.remote_button_watchers)
        self.assertIn((button.id, None), [(call.args[0].id, call.args[1]) for call in on_change.call_args_list])
