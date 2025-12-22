from unittest import mock

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class AutomationAiAssistantTests(BaseSimoTestCase):
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
            config={'autostart': True, 'autorestart': True, 'code': ''},
            meta={},
            value='stopped',
        )

    def test_ai_assistant_returns_internal_error_when_instance_context_is_missing(self):
        with (
            mock.patch('simo.automation.controllers.dynamic_settings', {'core__hub_uid': 'h', 'core__hub_secret': 's'}),
            mock.patch('simo.automation.controllers.get_current_instance', autospec=True, return_value=None),
            mock.patch('simo.automation.controllers.get_current_state', autospec=True, return_value={}),
            mock.patch('simo.automation.controllers.get_current_user', autospec=True, return_value=None),
            mock.patch('builtins.print'),
        ):
            out = self.comp.controller.ai_assistant('do it')

        self.assertEqual(out['status'], 'error')
        self.assertIn('Internal error', out['result'])

    def test_ai_assistant_returns_connection_error_on_requests_failure(self):
        with (
            mock.patch('simo.automation.controllers.dynamic_settings', {'core__hub_uid': 'h', 'core__hub_secret': 's'}),
            mock.patch('simo.automation.controllers.get_current_instance', autospec=True, return_value=self.inst),
            mock.patch('simo.automation.controllers.get_current_state', autospec=True, return_value={}),
            mock.patch('simo.automation.controllers.get_current_user', autospec=True, return_value=None),
            mock.patch('simo.automation.controllers.requests.post', side_effect=Exception('down')),
        ):
            out = self.comp.controller.ai_assistant('do it')

        self.assertEqual(out, {'status': 'error', 'result': 'Connection error'})

    def test_ai_assistant_parses_html_error_title(self):
        resp = mock.Mock(status_code=500, content=b"<html><title>Oops</title></html>")
        soup = mock.Mock()
        soup.title.string = 'Oops'

        with (
            mock.patch('simo.automation.controllers.dynamic_settings', {'core__hub_uid': 'h', 'core__hub_secret': 's'}),
            mock.patch('simo.automation.controllers.get_current_instance', autospec=True, return_value=self.inst),
            mock.patch('simo.automation.controllers.get_current_state', autospec=True, return_value={}),
            mock.patch('simo.automation.controllers.get_current_user', autospec=True, return_value=None),
            mock.patch('simo.automation.controllers.requests.post', return_value=resp),
            mock.patch('simo.automation.controllers.BeautifulSoup', autospec=True, return_value=soup),
        ):
            out = self.comp.controller.ai_assistant('do it')

        self.assertEqual(out['status'], 'error')
        self.assertIn('Server error 500: Oops', out['result'])

    def test_ai_assistant_success_returns_script_and_description(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {'script': 'print(1)', 'description': 'desc'}

        with (
            mock.patch('simo.automation.controllers.dynamic_settings', {'core__hub_uid': 'h', 'core__hub_secret': 's'}),
            mock.patch('simo.automation.controllers.get_current_instance', autospec=True, return_value=self.inst),
            mock.patch('simo.automation.controllers.get_current_state', autospec=True, return_value={}),
            mock.patch('simo.automation.controllers.get_current_user', autospec=True, return_value=None),
            mock.patch('simo.automation.controllers.requests.post', return_value=resp) as post,
        ):
            out = self.comp.controller.ai_assistant('wish', current_code='cur')

        self.assertEqual(out, {'status': 'success', 'result': 'print(1)', 'description': 'desc'})
        post.assert_called_once()
