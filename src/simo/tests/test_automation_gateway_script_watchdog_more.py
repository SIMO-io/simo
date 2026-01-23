import time

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

