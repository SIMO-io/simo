from unittest import mock

from django.core.exceptions import ValidationError
from django.test import override_settings

from simo.core.models import Gateway, Zone, Component

from .base import BaseSimoTestCase, BaseSimoTransactionTestCase, mk_instance


class ScriptControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.automation.gateways.AutomationsGatewayHandler')

        from simo.automation.controllers import Script

        self.comp = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='script',
            controller_uid=Script.uid,
            config={'autostart': True, 'autorestart': True, 'code': 'print("old")'},
            meta={},
            value='stopped',
        )

    def test_validate_val_rejects_invalid_before_send(self):
        from simo.automation.controllers import Script
        from simo.core.controllers import BEFORE_SEND

        controller = Script(self.comp)
        with self.assertRaises(ValidationError):
            controller._validate_val('bad', occasion=BEFORE_SEND)

    def test_toggle_sends_stop_when_running(self):
        self.comp.value = 'running'
        self.comp.save(update_fields=['value'])

        with mock.patch('simo.automation.controllers.Script.send', autospec=True) as send:
            self.comp.controller.toggle()
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1], 'stop')

    def test_toggle_sends_start_when_not_running(self):
        self.comp.value = 'stopped'
        self.comp.save(update_fields=['value'])

        with mock.patch('simo.automation.controllers.Script.send', autospec=True) as send:
            self.comp.controller.toggle()
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1], 'start')

    def test_start_persists_new_code_on_send(self):
        self.comp.config['code'] = 'print("old")'
        self.comp.save(update_fields=['config'])

        # BaseSimoTestCase already blocks MQTT side effects.
        self.comp.controller.start(new_code='print("new")')

        self.comp.refresh_from_db()
        self.assertEqual(self.comp.config.get('code'), 'print("new")')


class ScriptConfigChangeSignalTests(BaseSimoTransactionTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.automation.gateways.AutomationsGatewayHandler')

        from simo.automation.controllers import Script

        self.comp = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='script',
            controller_uid=Script.uid,
            config={'autostart': True, 'autorestart': True, 'code': 'print("old")'},
            meta={},
            value='running',
        )

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_config_change_while_running_triggers_stop_and_restart(self):
        from simo.automation.controllers import Script

        with (
            mock.patch('simo.automation.controllers.Script.stop', autospec=True) as stop,
            mock.patch('simo.automation.controllers.Script.start', autospec=True) as start,
            mock.patch('simo.automation.models.time.sleep', autospec=True),
        ):
            self.comp.config['code'] = 'print("changed")'
            self.comp.save(update_fields=['config'])

        stop.assert_called_once()
        start.assert_called_once()

    def test_delete_triggers_stop(self):
        from simo.automation.controllers import Script

        with mock.patch('simo.automation.controllers.Script.stop', autospec=True) as stop:
            self.comp.delete()
        stop.assert_called_once()
