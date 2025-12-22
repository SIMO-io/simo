from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase


class TemplateContextTests(SimpleTestCase):
    def test_context_for_anonymous_user_has_no_instances(self):
        from simo.core.context import additional_templates_context

        req = SimpleNamespace(user=AnonymousUser(), path='/')

        with (
            mock.patch('simo.core.context.get_self_ip', autospec=True, return_value='1.2.3.4'),
            mock.patch('simo.core.context.is_update_available', autospec=True, return_value=False),
            mock.patch('simo.core.context.get_current_instance', autospec=True, return_value=None),
            mock.patch('simo.core.context.dynamic_settings', {'x': 1}),
            mock.patch('simo.core.context.pkg_resources.get_distribution', autospec=True, side_effect=Exception('nope')),
        ):
            ctx = additional_templates_context(req)

        self.assertEqual(ctx['hub_ip'], '1.2.3.4')
        self.assertEqual(ctx['dynamic_settings'], {'x': 1})
        self.assertEqual(ctx['current_version'], 'dev')
        self.assertEqual(ctx['update_available'], False)
        self.assertEqual(list(ctx['instances']), [])
        self.assertIsNone(ctx['current_instance'])

    def test_admin_context_collects_todos_from_apps(self):
        from simo.core.context import additional_templates_context

        req = SimpleNamespace(user=AnonymousUser(), path='/admin/')
        fake_app = SimpleNamespace(name='fakeapp')

        todos_module = SimpleNamespace(
            todo_a=lambda: [{'title': 'a'}],
            todo_b=lambda: [{'title': 'b1'}, {'title': 'b2'}],
            not_callable=123,
        )
        fake_importlib = SimpleNamespace(import_module=mock.Mock(return_value=todos_module))

        with (
            mock.patch('simo.core.context.apps.app_configs', {'fakeapp': fake_app}),
            mock.patch('simo.core.context.importlib', fake_importlib),
            mock.patch('simo.core.context.get_self_ip', autospec=True, return_value='1.2.3.4'),
            mock.patch('simo.core.context.is_update_available', autospec=True, return_value=False),
            mock.patch('simo.core.context.get_current_instance', autospec=True, return_value=None),
        ):
            ctx = additional_templates_context(req)

        titles = [t['title'] for t in ctx['todos']]
        self.assertEqual(titles, ['a', 'b1', 'b2'])
        for todo in ctx['todos']:
            self.assertEqual(todo['app_name'], 'fakeapp')
