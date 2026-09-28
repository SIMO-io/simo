import multiprocessing
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from .base import BaseSimoTestCase


class _Worker:
    def __init__(self):
        self.pid = 123
        self.exit_event = mock.Mock()
        self.alive = True
        self.terminated = False
        self.killed = False

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.alive = False


class GatewaysManagerLifecycleTests(BaseSimoTestCase):
    def test_mqtt_startup_cancellation_always_runs_shutdown(self):
        from simo.core.management.commands import gateways_manager as module

        manager = module.GatewaysManager()
        gateway = SimpleNamespace(id=1)
        exit_event = multiprocessing.Event()
        with (
            mock.patch.object(module.Gateway.objects, 'filter', return_value=[]),
            mock.patch.object(module.Gateway.objects, 'all', return_value=[gateway]),
            mock.patch.object(manager, 'start_gateway', autospec=True),
            mock.patch.object(manager, 'shutdown', wraps=manager.shutdown) as shutdown,
            mock.patch.object(module, 'connect_with_retry', return_value=False),
            mock.patch.object(module, 'install_reconnect_handler'),
            mock.patch.object(module.mqtt, 'Client'),
        ):
            manager.start(exit_event)

        manager.start_gateway.assert_called_once_with(gateway)
        shutdown.assert_called_once()

    def test_shutdown_escalates_and_reaps_uncooperative_worker(self):
        from simo.core.management.commands.gateways_manager import GatewaysManager

        manager = GatewaysManager()
        worker = _Worker()
        with mock.patch.object(manager, '_join_workers'):
            manager._reap_workers([worker])

        worker.exit_event.set.assert_called_once()
        self.assertTrue(worker.terminated)
        self.assertTrue(worker.killed)

    def test_supervisor_stops_the_gateway_process_group(self):
        from simo.core.management.commands import gateways_manager as module

        supervisor_conf = (
            Path(module.__file__).parents[1]
            / '_hub_template' / 'hub' / 'supervisor.conf'
        ).read_text()
        gateway_program = supervisor_conf.split('[program:simo-gateways]', 1)[1]
        gateway_program = gateway_program.split('[program:', 1)[0]

        self.assertIn('stopasgroup=true', gateway_program)
        self.assertIn('killasgroup=true', gateway_program)
        self.assertIn('stopsignal=TERM', gateway_program)
