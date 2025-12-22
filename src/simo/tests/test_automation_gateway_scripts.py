import multiprocessing
import threading
from unittest import mock

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class FakeMqttClient:
    def __init__(self):
        self.on_connect = None
        self.on_message = None

    def username_pw_set(self, *_args, **_kwargs):
        return None

    def reconnect_delay_set(self, **_kwargs):
        return None


class InlineThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class AutomationGatewayScriptsTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.automation.gateways import AutomationsGatewayHandler

        self.gw, _ = Gateway.objects.get_or_create(type=AutomationsGatewayHandler.uid)

        from simo.automation.controllers import Script

        self.script = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='script',
            controller_uid=Script.uid,
            config={'code': 'print("x")'},
            meta={},
            value='stopped',
        )
        # Ensure controller methods are prepared on the component (component.set()).
        _ = self.script.controller

    def _mk_gateway(self):
        from simo.automation.gateways import AutomationsGatewayHandler

        with mock.patch('simo.core.gateways.mqtt.Client', autospec=True, side_effect=FakeMqttClient):
            handler = AutomationsGatewayHandler(self.gw)
        handler.logger = mock.Mock()
        return handler

    def test_script_run_handler_uses_controller__run_when_present(self):
        from simo.automation.gateways import ScriptRunHandler

        handler = ScriptRunHandler(1, multiprocessing.Event())
        handler.exit_event = multiprocessing.Event()
        handler.component = mock.Mock()
        controller = mock.Mock()
        controller._run = mock.Mock()
        handler.component.controller = controller

        handler.run_code()

        self.assertTrue(handler.exit_in_use.is_set())
        self.assertIs(controller.exit_event, handler.exit_event)
        controller._run.assert_called_once()

    def test_script_run_handler_no_code_marks_finished(self):
        from simo.automation.gateways import ScriptRunHandler

        handler = ScriptRunHandler(1, multiprocessing.Event())
        handler.exit_event = multiprocessing.Event()
        handler.component = mock.Mock()
        handler.component.controller = mock.Mock(spec=[])
        handler.component.config = {}

        handler.run_code()

        self.assertEqual(handler.component.value, 'finished')
        handler.component.save.assert_called_once()

    def test_script_run_handler_exec_automation_runs_with_exit_event(self):
        from simo.automation.gateways import ScriptRunHandler

        handler = ScriptRunHandler(1, multiprocessing.Event())
        handler.exit_event = multiprocessing.Event()
        handler.component = mock.Mock()
        handler.component.controller = mock.Mock(spec=[])
        handler.component.config = {
            'code': (
                'class Automation:\n'
                '    def __init__(self):\n'
                '        self.called = False\n'
                '    def run(self, exit_event):\n'
                '        exit_event.is_set()\n'
            )
        }

        with mock.patch('simo.automation.gateways.time.time', autospec=True, side_effect=[0.0, 0.1]):
            handler.run_code()

        self.assertTrue(handler.exit_in_use.is_set())
        self.assertFalse(handler.exin_in_use_fail.is_set())

    def test_script_run_handler_exec_automation_falls_back_to_noargs_on_failure(self):
        from simo.automation.gateways import ScriptRunHandler

        handler = ScriptRunHandler(1, multiprocessing.Event())
        handler.exit_event = multiprocessing.Event()
        handler.component = mock.Mock()
        handler.component.controller = mock.Mock(spec=[])
        handler.component.config = {
            'code': (
                'class Automation:\n'
                '    def run(self, exit_event=None):\n'
                '        if exit_event is not None:\n'
                '            raise RuntimeError("no args")\n'
            )
        }

        with mock.patch('simo.automation.gateways.time.time', autospec=True, side_effect=[0.0, 0.1]):
            handler.run_code()

        self.assertTrue(handler.exit_in_use.is_set())
        self.assertTrue(handler.exin_in_use_fail.is_set())

    def test_script_run_handler_exec_without_automation_class_does_not_set_exit_in_use(self):
        from simo.automation.gateways import ScriptRunHandler

        handler = ScriptRunHandler(1, multiprocessing.Event())
        handler.exit_event = multiprocessing.Event()
        handler.component = mock.Mock()
        handler.component.controller = mock.Mock(spec=[])
        handler.component.config = {'code': 'x = 1\n'}

        handler.run_code()
        self.assertFalse(handler.exit_in_use.is_set())

    def test_start_script_tracks_new_process(self):
        from simo.automation import gateways as gw_mod

        handler = self._mk_gateway()

        proc = mock.Mock()
        with mock.patch.object(gw_mod, 'ScriptRunHandler', autospec=True, return_value=proc):
            handler.start_script(self.script)

        proc.start.assert_called_once()
        self.assertIn(self.script.id, handler.running_scripts)

    def test_start_script_does_nothing_if_running_and_not_terminating(self):
        handler = self._mk_gateway()

        proc = mock.Mock()
        proc.is_alive.return_value = True
        handler.running_scripts[self.script.id] = {'proc': proc, 'start_time': 0}

        handler.start_script(self.script)

        proc.start.assert_not_called()

    def test_start_script_kills_existing_when_terminating(self):
        from simo.automation import gateways as gw_mod

        handler = self._mk_gateway()
        old_proc = mock.Mock()
        old_proc.is_alive.return_value = True
        handler.running_scripts[self.script.id] = {'proc': old_proc, 'start_time': 0}
        handler.terminating_scripts.add(self.script.id)

        new_proc = mock.Mock()
        with mock.patch.object(gw_mod, 'ScriptRunHandler', autospec=True, return_value=new_proc):
            handler.start_script(self.script)

        old_proc.kill.assert_called_once()
        new_proc.start.assert_called_once()

    def test_stop_script_updates_component_when_not_tracked(self):
        handler = self._mk_gateway()
        self.script.value = 'running'
        self.script.save(update_fields=['value'])

        handler.stop_script(self.script, stop_status='stopped')

        self.script.refresh_from_db()
        self.assertEqual(self.script.value, 'stopped')

    def test_stop_script_sets_exit_event_and_terminates_process_noncooperative(self):
        from simo.automation import gateways as gw_mod

        handler = self._mk_gateway()

        proc = mock.Mock()
        proc.exit_event = multiprocessing.Event()
        proc.exit_in_use = multiprocessing.Event()
        proc.exin_in_use_fail = multiprocessing.Event()
        proc.watchers_cleaned = multiprocessing.Event()
        proc.watchers_cleaned.set()
        proc.is_alive.side_effect = [True, False]

        handler.running_scripts[self.script.id] = {'proc': proc, 'start_time': 0}

        logger = mock.Mock()
        logger.handlers = ['x']

        times = iter([0.0, 1.0, 2.0, 3.0])

        with (
            mock.patch.object(gw_mod.threading, 'Thread', autospec=True, side_effect=lambda *a, **k: InlineThread(k['target'])),
            mock.patch.object(gw_mod.time, 'time', autospec=True, side_effect=lambda: next(times)),
            mock.patch.object(gw_mod.time, 'sleep', autospec=True, side_effect=lambda *_a, **_k: None),
            mock.patch.object(gw_mod, 'get_component_logger', autospec=True, return_value=logger),
        ):
            handler.stop_script(self.script, stop_status='error')

        self.assertTrue(proc.exit_event.is_set())
        proc.terminate.assert_called_once()
        proc.kill.assert_called()
        self.assertNotIn(self.script.id, handler.running_scripts)
        self.assertNotIn(self.script.id, handler.terminating_scripts)
