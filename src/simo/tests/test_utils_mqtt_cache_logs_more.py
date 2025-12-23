from __future__ import annotations

import asyncio
import threading
from unittest import mock
from types import SimpleNamespace

from django.test import SimpleTestCase


class TestMqttHelpers(SimpleTestCase):
    def test_log_falls_back_to_print(self):
        from simo.core.utils.mqtt import _log

        with mock.patch('builtins.print') as printer:
            _log(None, 'info', 'hello')
        printer.assert_called_once_with('hello')

    def test_connect_with_retry_success_first_attempt(self):
        from simo.core.utils.mqtt import connect_with_retry

        client = mock.Mock()
        logger = mock.Mock()
        ok = connect_with_retry(client, logger=logger, retry_delay=0)
        self.assertTrue(ok)
        client.connect.assert_called_once()
        logger.info.assert_not_called()
        logger.warning.assert_not_called()

    def test_connect_with_retry_reconnect_message(self):
        from simo.core.utils.mqtt import connect_with_retry

        client = mock.Mock()
        client.connect.side_effect = [RuntimeError('nope'), RuntimeError('nope'), None]
        logger = mock.Mock()
        stop_event = threading.Event()
        with (
            mock.patch('time.sleep') as sleep,
            mock.patch.object(stop_event, 'wait', return_value=False),
        ):
            ok = connect_with_retry(
                client,
                logger=logger,
                retry_delay=0,
                stop_event=stop_event,
            )
        self.assertTrue(ok)
        self.assertEqual(client.connect.call_count, 3)
        self.assertGreaterEqual(logger.warning.call_count, 2)
        logger.info.assert_called_once()
        sleep.assert_not_called()

    def test_connect_with_retry_stop_event_aborts(self):
        from simo.core.utils.mqtt import connect_with_retry

        stop_event = threading.Event()
        stop_event.set()
        client = mock.Mock()
        ok = connect_with_retry(client, stop_event=stop_event, retry_delay=0)
        self.assertFalse(ok)
        client.connect.assert_not_called()

    def test_install_reconnect_handler_rc_success_is_noop(self):
        import paho.mqtt.client as mqtt

        from simo.core.utils.mqtt import install_reconnect_handler

        client = mock.Mock()
        install_reconnect_handler(client)
        client.on_disconnect(client, None, mqtt.MQTT_ERR_SUCCESS)
        client.reconnect.assert_not_called()

    def test_install_reconnect_handler_user_handler_errors_are_logged(self):
        from simo.core.utils.mqtt import install_reconnect_handler

        client = mock.Mock()
        logger = mock.Mock()

        def _bad_handler(*_args, **_kwargs):
            raise RuntimeError('boom')

        install_reconnect_handler(client, logger=logger, user_handler=_bad_handler)
        with mock.patch('threading.Thread') as thread:
            client.on_disconnect(client, None, 1)
        logger.error.assert_called_once()
        thread.assert_called_once()

    def test_install_reconnect_handler_lock_prevents_parallel_reconnects(self):
        from simo.core.utils.mqtt import install_reconnect_handler

        client = mock.Mock()

        class DummyThread:
            def __init__(self, *, target, daemon):
                self.target = target
                self.daemon = daemon

            def start(self):
                # Intentionally never runs target, so lock stays held.
                return None

        with mock.patch('threading.Thread', side_effect=lambda **kw: DummyThread(**kw)) as thread:
            install_reconnect_handler(client)
            client.on_disconnect(client, None, 1)
            client.on_disconnect(client, None, 1)
        self.assertEqual(thread.call_count, 1)


class TestCacheHelper(SimpleTestCase):
    def test_get_cached_data_builds_and_caches(self):
        from simo.core.utils.cache import get_cached_data

        cache_obj = mock.Mock()
        cache_obj.get.return_value = 'NONE!'
        caches = {'default': cache_obj}
        called = []

        def rebuild_fn():
            called.append(True)
            return {'ok': True}

        with (
            mock.patch('simo.core.utils.cache.caches', caches),
            mock.patch(
                'simo.core.utils.cache.settings',
                SimpleNamespace(CACHES={'default': {'TIMEOUT': 123}}),
            ),
            mock.patch('builtins.print') as printer,
        ):
            value = get_cached_data('k', rebuild_fn)

        self.assertEqual(value, {'ok': True})
        self.assertEqual(called, [True])
        cache_obj.set.assert_called_once_with('k', {'ok': True}, 123)
        printer.assert_called_once()

    def test_get_cached_data_returns_cached_value(self):
        from simo.core.utils.cache import get_cached_data

        cache_obj = mock.Mock()
        cache_obj.get.return_value = 999
        caches = {'default': cache_obj}
        rebuild_fn = mock.Mock(return_value=123)

        with mock.patch('simo.core.utils.cache.caches', caches):
            value = get_cached_data('k', rebuild_fn)
        self.assertEqual(value, 999)
        rebuild_fn.assert_not_called()


class TestLogsHelpers(SimpleTestCase):
    def test_stream_to_logger_buffers_until_newline(self):
        from simo.core.utils.logs import StreamToLogger

        logger = mock.Mock()
        stream = StreamToLogger(logger)
        stream.write('hello')
        logger.log.assert_not_called()
        stream.write(' world\n')
        logger.log.assert_called_once()

    def test_stream_to_logger_flush_logs_remainder(self):
        from simo.core.utils.logs import StreamToLogger

        logger = mock.Mock()
        stream = StreamToLogger(logger)
        stream.write('partial')
        stream.flush()
        logger.log.assert_called_once()

    def test_propagate_exceptions_marks_exception_caught_and_logs_once(self):
        from simo.core.utils.logs import propagate_exceptions

        exc = ValueError('x')

        async def boom():
            raise exc

        wrapped = propagate_exceptions(boom)
        with mock.patch('simo.core.utils.logs.logger') as log:
            with self.assertRaises(ValueError) as ctx1:
                asyncio.run(wrapped())
            with self.assertRaises(ValueError) as ctx2:
                asyncio.run(wrapped())

        self.assertTrue(getattr(ctx1.exception, 'caught'))
        self.assertTrue(getattr(ctx2.exception, 'caught'))
        log.error.assert_called_once()
