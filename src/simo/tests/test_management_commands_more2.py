from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase


class TestRepublishMqttStateCommand(SimpleTestCase):
    def test_republish_counts_all_objects(self):
        from simo.core.management.commands import republish_mqtt_state

        inst = SimpleNamespace(id=1)
        zone = SimpleNamespace(name='Z')
        cat = SimpleNamespace(name='C', last_modified='x')
        comp = SimpleNamespace(
            value=1,
            last_change='t',
            arm_status=None,
            battery_level=50,
            alive=True,
            meta={},
        )
        iu = SimpleNamespace(at_home=True, last_seen='x', phone_on_charge=False)

        qs = mock.Mock()
        qs.__iter__ = lambda self=qs: iter([inst])
        qs.filter.return_value = qs

        oce = mock.Mock()
        oce.return_value.publish = mock.Mock()

        cmd = republish_mqtt_state.Command()
        with (
            mock.patch.object(republish_mqtt_state.Instance.objects, 'filter', return_value=qs),
            mock.patch.object(republish_mqtt_state.Zone.objects, 'filter', return_value=[zone]),
            mock.patch.object(republish_mqtt_state.Category.objects, 'filter', return_value=[cat]),
            mock.patch.object(republish_mqtt_state.Component.objects, 'filter', return_value=[comp]),
            mock.patch.object(republish_mqtt_state.InstanceUser.objects, 'filter', return_value=[iu]),
            mock.patch.object(republish_mqtt_state, 'ObjectChangeEvent', oce),
        ):
            cmd.handle(instance=None)

        # 1 zone + 1 cat + 1 component + 1 instance user
        self.assertEqual(oce.call_count, 4)
        self.assertEqual(oce.return_value.publish.call_count, 4)


class TestRunGatewayCommand(SimpleTestCase):
    def test_runs_gateway(self):
        from simo.core.management.commands import run_gateway

        gw = mock.Mock()
        gw.run = mock.Mock()

        cmd = run_gateway.Command()
        with (
            mock.patch.object(run_gateway.Gateway.objects, 'get', return_value=gw),
            mock.patch.object(run_gateway.multiprocessing, 'Event', autospec=True) as ev,
        ):
            exit_event = mock.Mock()
            ev.return_value = exit_event
            cmd.handle(gateway_id=[1])

        gw.run.assert_called_once_with(exit_event)

    def test_keyboard_interrupt_sets_exit_event(self):
        from simo.core.management.commands import run_gateway

        gw = mock.Mock()

        def _run(_ev):
            raise KeyboardInterrupt()

        gw.run = _run

        cmd = run_gateway.Command()
        exit_event = mock.Mock()
        with (
            mock.patch.object(run_gateway.Gateway.objects, 'get', return_value=gw),
            mock.patch.object(run_gateway.multiprocessing, 'Event', return_value=exit_event),
        ):
            cmd.handle(gateway_id=[1])

        exit_event.set.assert_called_once()


class TestOnHttpStartCommand(SimpleTestCase):
    def test_handle_auto_creates_gateways_best_effort(self):
        from simo.core.management.commands import on_http_start

        class Handler:
            name = 'Handler'
            auto_create = True

            class config_form:
                def __init__(self, instance=None):
                    self.fields = {
                        'a': SimpleNamespace(initial=1),
                        'log': SimpleNamespace(initial='skip'),
                    }

        gw_obj = mock.Mock()
        gw_obj.start = mock.Mock()

        cmd = on_http_start.Command()
        with (
            mock.patch.object(on_http_start, 'prepare_mosquitto', autospec=True),
            mock.patch.object(on_http_start, 'update_auto_update', autospec=True),
            mock.patch('simo.core.tasks.maybe_update_to_latest.delay', autospec=True),
            mock.patch('simo.core.utils.type_constants.GATEWAYS_MAP', {'uid': Handler}),
            mock.patch('simo.core.models.Gateway.objects.get_or_create', return_value=(gw_obj, True)) as get_or_create,
            mock.patch('simo.core.management.commands.on_http_start.apps') as apps,
            mock.patch('simo.core.management.commands.on_http_start.importlib.import_module', side_effect=ModuleNotFoundError),
        ):
            apps.app_configs.items.return_value = [
                ('auth', SimpleNamespace(name='auth')),
                ('x', SimpleNamespace(name='x')),
            ]

            cmd.handle()

        get_or_create.assert_called_once()
        gw_obj.start.assert_called_once()
