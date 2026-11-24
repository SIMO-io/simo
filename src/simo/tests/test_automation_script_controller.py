from unittest import mock

from django.contrib.admin import AdminSite
from django.core.exceptions import ValidationError
from django.test import RequestFactory, override_settings

from simo.core.admin import ComponentAdmin
from simo.core.models import Gateway, Zone, Component
from simo.users.utils import introduce_user

from .base import BaseSimoTestCase, BaseSimoTransactionTestCase, mk_instance, mk_user


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
        introduce_user(mk_user('master@example.com', 'Master', is_master=True))
        self.comp.controller.start(new_code='print("new")')

        self.comp.refresh_from_db()
        self.assertEqual(self.comp.config.get('code'), 'print("new")')

    def test_admin_saves_script_without_breach_delay_type(self):
        admin = ComponentAdmin(Component, AdminSite())
        self.comp.breach_delay_type = 'accumulated'
        self.comp.save(update_fields=['breach_delay_type'])
        generated = {
            'status': 'success',
            'result': 'print("generated")',
            'description': 'Generated script',
        }
        for prompt, code, show_in_app in (
            ('', 'print("manual")', False),
            ('Change hold to double click', 'print("manual")', False),
            ('', generated['result'], True),
        ):
            with self.subTest(prompt=prompt, code=code, show_in_app=show_in_app):
                request = RequestFactory().post('/', {
                    'name': self.comp.name,
                    'zone': self.zone.pk,
                    'code': code,
                    'notes': self.comp.notes or '',
                    'assistant_request': prompt,
                    'show_in_app': 'on' if show_in_app else '',
                })
                form_class = admin.get_form(request, self.comp, change=True)
                with mock.patch.object(self.comp, 'ai_assistant', return_value=generated) as assistant:
                    form = form_class(request.POST, request.FILES, instance=self.comp)
                    self.assertTrue(form.is_valid(), form.errors)
                    obj = admin.save_form(request, form, change=True)
                    admin.save_model(request, obj, form, change=True)
                    self.assertEqual(assistant.call_count, int(bool(prompt)))
                self.comp.refresh_from_db()
                self.assertEqual(self.comp.config['code'], generated['result'] if prompt else code)
                if prompt:
                    self.assertEqual(self.comp.notes, generated['description'])
                self.assertEqual(self.comp.show_in_app, show_in_app)
                self.assertEqual(self.comp.breach_delay_type, 'accumulated')


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
