import time
from unittest import mock

from simo.core.models import Gateway, Zone, Component

from .base import BaseSimoTestCase, mk_instance


class _StuckProc:
    def __init__(self):
        self.killed = False

    def is_alive(self):
        return True

    def kill(self):
        self.killed = True


class AutomationGatewayScriptWatchdogTests(BaseSimoTestCase):
    def test_startup_timeout_kills_stuck_script_process(self):
        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.automation.gateways.AutomationsGatewayHandler')

        from simo.automation.controllers import PresenceLighting

        script = Component.objects.create(
            name='S',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='script',
            controller_uid=PresenceLighting.uid,
            config={'keep_alive': True, 'autostart': True},
            meta={},
            value='error',
        )

        handler = gw.handler
        stuck = _StuckProc()
        handler.running_scripts[script.id] = {
            'proc': stuck,
            'start_time': time.time() - 120,
        }

        handler.watch_scripts()

        self.assertTrue(stuck.killed)
        self.assertNotIn(script.id, handler.running_scripts)

    def test_watchdog_stops_script_marked_stopped_but_with_live_pid(self):
        inst = mk_instance('inst-b', 'B')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.automation.gateways.AutomationsGatewayHandler')

        from simo.automation.controllers import PresenceLighting

        script = Component.objects.create(
            name='S2',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='script',
            controller_uid=PresenceLighting.uid,
            config={},
            meta={'pid': 12345},
            value='stopped',
        )

        handler = gw.handler

        with (
            mock.patch.object(handler, '_pid_exists', autospec=True, return_value=True),
            mock.patch.object(handler, '_stop_untracked_script_pid', autospec=True, return_value=True) as stop_pid,
            mock.patch('simo.automation.gateways.get_component_logger', autospec=True, return_value=mock.Mock()),
        ):
            handler.watch_scripts()

        stop_pid.assert_called_once()
