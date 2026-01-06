from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase


class DummyExecutor:
    def __init__(self, max_workers=1):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def map(self, fn, iterable):
        return [fn(i) for i in iterable]


class TestMcpExecuteComponentMethods(SimpleTestCase):
    def test_empty_operations_returns_empty(self):
        from simo.core.mcp import execute_component_methods

        inst = SimpleNamespace(timezone='UTC')
        user = SimpleNamespace(is_master=True)

        with (
            mock.patch('simo.core.mcp.get_current_user', return_value=user),
            mock.patch('simo.core.mcp.get_current_instance', return_value=inst),
            mock.patch('simo.core.mcp.check_throttle', return_value=0),
        ):
            out = asyncio.run(execute_component_methods.fn([]))
        self.assertEqual(out, [])

    def test_throttled_raises_permission_error(self):
        from simo.core.mcp import execute_component_methods

        inst = SimpleNamespace(timezone='UTC')
        user = SimpleNamespace(is_master=True)

        with (
            mock.patch('simo.core.mcp.get_current_user', return_value=user),
            mock.patch('simo.core.mcp.get_current_instance', return_value=inst),
            mock.patch('simo.core.mcp.check_throttle', return_value=1),
        ):
            with self.assertRaises(PermissionError):
                asyncio.run(execute_component_methods.fn([[1, 'x']]))

    def test_method_invocation_positional_and_keyword(self):
        from simo.core.mcp import execute_component_methods

        inst = SimpleNamespace(timezone='UTC')
        user = SimpleNamespace(is_master=True)

        component = mock.Mock()
        component.controller = SimpleNamespace(masters_only=False)
        component.get_controller_methods.return_value = ['sum', 'kw']
        component.prepare_controller = mock.Mock()

        component.sum = mock.Mock(return_value=3)
        component.kw = mock.Mock(return_value='ok')

        def get_component(**_kwargs):
            return component

        with (
            mock.patch('simo.core.mcp.get_current_user', return_value=user),
            mock.patch('simo.core.mcp.get_current_instance', return_value=inst),
            mock.patch('simo.core.mcp.check_throttle', return_value=0),
            mock.patch('simo.core.mcp.Component.objects.get', side_effect=get_component),
            mock.patch('simo.core.mcp.ThreadPoolExecutor', DummyExecutor),
        ):
            out = asyncio.run(
                execute_component_methods.fn(
                    [
                        [1, 'sum', [1, 2], None],
                        {'component_id': 1, 'method_name': 'kw', 'args': None, 'kwargs': {'a': 1}},
                    ]
                )
            )

        self.assertEqual(out, [3, 'ok'])
        component.sum.assert_called_once_with(1, 2)
        component.kw.assert_called_once_with(a=1)

    def test_masters_only_controller_allows_non_master_method_invocation(self):
        from simo.core.mcp import execute_component_methods

        inst = SimpleNamespace(timezone='UTC')
        user = SimpleNamespace(is_master=False)

        component = mock.Mock()
        component.controller = SimpleNamespace(masters_only=True)
        component.get_controller_methods.return_value = ['x']
        component.prepare_controller = mock.Mock()
        component.x = mock.Mock(return_value='ok')

        with (
            mock.patch('simo.core.mcp.get_current_user', return_value=user),
            mock.patch('simo.core.mcp.get_current_instance', return_value=inst),
            mock.patch('simo.core.mcp.check_throttle', return_value=0),
            mock.patch('simo.core.mcp.Component.objects.get', return_value=component),
            mock.patch('simo.core.mcp.ThreadPoolExecutor', DummyExecutor),
        ):
            out = asyncio.run(execute_component_methods.fn([[1, 'x']]))

        self.assertEqual(out, ['ok'])

    def test_method_not_allowed_rejected(self):
        from simo.core.mcp import execute_component_methods

        inst = SimpleNamespace(timezone='UTC')
        user = SimpleNamespace(is_master=True)

        component = mock.Mock()
        component.controller = SimpleNamespace(masters_only=False)
        component.get_controller_methods.return_value = ['allowed']
        component.prepare_controller = mock.Mock()

        with (
            mock.patch('simo.core.mcp.get_current_user', return_value=user),
            mock.patch('simo.core.mcp.get_current_instance', return_value=inst),
            mock.patch('simo.core.mcp.check_throttle', return_value=0),
            mock.patch('simo.core.mcp.Component.objects.get', return_value=component),
            mock.patch('simo.core.mcp.ThreadPoolExecutor', DummyExecutor),
        ):
            with self.assertRaises(PermissionError):
                asyncio.run(execute_component_methods.fn([[1, 'blocked']]))


class TestMcpSimpleTools(SimpleTestCase):
    def test_get_unix_timestamp(self):
        from simo.core.mcp import get_unix_timestamp

        with mock.patch('simo.core.mcp.timezone.now', return_value=SimpleNamespace(timestamp=lambda: 123.9)):
            out = asyncio.run(get_unix_timestamp.fn())
        self.assertEqual(out, 123)

    def test_update_ai_memory(self):
        from simo.core.mcp import update_ai_memory

        inst = SimpleNamespace(ai_memory='', save=mock.Mock())
        with mock.patch('simo.core.mcp.get_current_instance', return_value=inst):
            asyncio.run(update_ai_memory.fn('hello'))

        self.assertEqual(inst.ai_memory, 'hello')
        inst.save.assert_called_once()
