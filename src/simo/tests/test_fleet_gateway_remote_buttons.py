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

        button = Component.objects.create(
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
        # New components initialize to the controller default ('up').
        Component.objects.filter(pk=button.pk).update(value=value)
        button.value = value
        return button

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

        with mock.patch('simo.fleet.controllers.FleetDeviceMixin._ctrl', autospec=True) as ctrl:
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

        with mock.patch('simo.fleet.controllers.FleetDeviceMixin._ctrl', autospec=True) as ctrl:
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
            mock.patch('simo.fleet.controllers.FleetDeviceMixin._ctrl', autospec=True) as ctrl,
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

    @staticmethod
    def _button_control_types():
        from simo.fleet import controllers
        from simo.core.controllers import ControllerBase

        return [
            cls for cls in vars(controllers).values()
            if isinstance(cls, type)
            and issubclass(cls, ControllerBase)
            and cls.__module__ == controllers.__name__
            and 'controls' in cls.config_form.base_fields
        ]

    def _make_controlled_component(self, controller, button, colonel=8):
        return Component.objects.create(
            name=controller.__name__,
            zone=self.zone,
            gateway=self.gw,
            base_type=controller.base_type,
            controller_uid=controller.uid,
            config={
                'colonel': colonel,
                'controls': [{'input': f'button-{button.id}', 'method': 'momentary'}],
            },
            meta={},
            value=controller.default_value,
        )

    def test_every_button_control_type_forwards_events_to_target_colonel(self):
        from simo.core.events import GatewayObjectCommand

        handler = self._mk_handler()
        button = self._make_button('Remote', 18)
        components = [
            self._make_controlled_component(controller, button)
            for controller in self._button_control_types()
        ]
        self.assertTrue(components)
        with mock.patch('simo.core.events.OnChangeMixin.on_change', autospec=True):
            handler.watch_buttons()

        self.assertEqual(
            handler.remote_button_targets,
            {button.id: {(component.id, 0) for component in components}},
        )
        for event in ('down', 'up', 'click', 'double-click', 'hold'):
            with self.subTest(event=event):
                button.value = event
                GatewayObjectCommand.publish.reset_mock()
                handler.on_remote_button_change(button)
                commands = [
                    call.args[0].data
                    for call in GatewayObjectCommand.publish.call_args_list
                ]
                self.assertCountEqual([cmd['id'] for cmd in commands], [c.id for c in components])
                for command in commands:
                    self.assertEqual(command['obj_pk'], 8)
                    self.assertEqual(command['command'], 'call')
                    self.assertEqual(command['method'], 'ctrl')
                    self.assertEqual(command['args'], [0, event, 'momentary'])

    def test_every_button_control_type_leaves_local_buttons_to_colonel(self):
        handler = self._mk_handler()
        button = self._make_button('Local', 8)
        for controller in self._button_control_types():
            self._make_controlled_component(controller, button)

        with mock.patch('simo.core.events.OnChangeMixin.on_change', autospec=True) as on_change:
            handler.watch_buttons()
        self.assertEqual(handler.remote_button_targets, {})
        on_change.assert_not_called()

    def test_toggle_button_preserves_method_and_control_number(self):
        from simo.core.events import GatewayObjectCommand
        from simo.fleet.controllers import Gate

        handler = self._mk_handler()
        button = self._make_button('Toggle', 18, value='up')
        gate = self._make_controlled_component(Gate, button)
        gate.config['controls'] = [
            {'pin_no': 5},
            {'button': str(button.id), 'method': 'toggle'},
        ]
        gate.save(update_fields=['config'])
        with mock.patch('simo.core.events.OnChangeMixin.on_change', autospec=True):
            handler.watch_buttons()

        GatewayObjectCommand.publish.reset_mock()
        handler.on_remote_button_change(button)
        GatewayObjectCommand.publish.assert_called_once()
        self.assertEqual(
            GatewayObjectCommand.publish.call_args.args[0].data['args'],
            [1, 'up', 'toggle'],
        )

    def test_removing_last_button_refreshes_watchers_for_every_control_type(self):
        from simo.core.events import GatewayObjectCommand
        from simo.core.middleware import introduce_instance
        from simo.fleet.models import Colonel, Interface

        introduce_instance(self.inst)
        colonel = Colonel.objects.create(instance=self.inst, uid='controls')
        interface = Interface.objects.create(colonel=colonel, no=1, type='dali')
        button = self._make_button('Remote', colonel.id + 1)
        for address, controller in enumerate(self._button_control_types()):
            with self.subTest(controller=controller.__name__):
                component = self._make_controlled_component(controller, button, colonel.id)
                if controller.family == 'dali':
                    component.config.update(interface=interface.id, dali_interface=1, da=address)
                component.save(update_fields=['config'])
                form = controller.config_form(
                    instance=component,
                    data={
                        'name': component.name,
                        'zone': self.zone.id,
                        'colonel': colonel.id,
                        'interface': interface.id,
                        'controls-TOTAL_FORMS': 0,
                        'controls-INITIAL_FORMS': 1,
                        'controls-MIN_NUM_FORMS': 0,
                        'controls-MAX_NUM_FORMS': 999,
                    },
                )
                self.assertTrue(form.is_valid(), form.errors)
                GatewayObjectCommand.publish.reset_mock()
                form.save()
                component.refresh_from_db()
                self.assertEqual(component.config['controls'], [])
                refresh_commands = [
                    call.args[0].data
                    for call in GatewayObjectCommand.publish.call_args_list
                    if call.args[0].data['command'] == 'watch_buttons'
                ]
                self.assertEqual(len(refresh_commands), 1)
                self.assertEqual(refresh_commands[0]['obj_pk'], component.pk)

    def test_unsaved_pwm_forms_do_not_publish_commands(self):
        from simo.core.events import GatewayObjectCommand
        from simo.core.middleware import introduce_instance
        from simo.fleet.controllers import PWMOutput, DC10VDriver
        from simo.fleet.models import Colonel

        introduce_instance(self.inst)
        colonel = Colonel.objects.create(instance=self.inst, uid='pwm-controls')
        button = self._make_button('Remote', colonel.id + 1)
        for controller in (PWMOutput, DC10VDriver):
            with self.subTest(controller=controller.__name__):
                component = self._make_controlled_component(controller, button, colonel.id)
                component.config['controls'] = []
                component.save(update_fields=['config'])
                form = controller.config_form(
                    instance=component,
                    data={
                        'name': component.name,
                        'zone': self.zone.id,
                        'colonel': colonel.id,
                        'controls-TOTAL_FORMS': 0,
                        'controls-INITIAL_FORMS': 0,
                    },
                )
                self.assertTrue(form.is_valid(), form.errors)
                GatewayObjectCommand.publish.reset_mock()
                form.save(commit=False)
                GatewayObjectCommand.publish.assert_not_called()
