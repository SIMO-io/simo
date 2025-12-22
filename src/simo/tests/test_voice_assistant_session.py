import asyncio
import time
from unittest import mock

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase


class VoiceAssistantSessionTests(SimpleTestCase):
    def _make_session(self):
        from simo.fleet.voice_assistant import VoiceAssistantSession

        class ConsumerStub:
            instance = None
            colonel = None

        def _discard_task(coro):
            try:
                coro.close()
            except Exception:
                pass
            return mock.Mock()

        with mock.patch('simo.fleet.voice_assistant.asyncio.create_task', side_effect=_discard_task):
            return VoiceAssistantSession(ConsumerStub())

    def test_on_audio_chunk_ignored_while_playing(self):
        session = self._make_session()
        session.playing = True

        async def run():
            await session.on_audio_chunk(b'\x00\x00')

        async_to_sync(run)()
        self.assertEqual(session.capture_buf, bytearray())
        self.assertFalse(session.active)

    def test_finalize_clears_buffer_and_schedules_cloud_task(self):
        session = self._make_session()

        scheduled = []

        def _capture_task(coro):
            scheduled.append(coro)
            return mock.Mock(done=lambda: False)

        session.capture_buf.extend(b'\x00\x00' * 10)
        session._rx_start_ts = time.time()
        session._rx_started = True

        async def run():
            with mock.patch('simo.fleet.voice_assistant.asyncio.create_task', side_effect=_capture_task):
                await session._finalize_utterance()

        async_to_sync(run)()
        self.assertEqual(session.capture_buf, bytearray())
        self.assertIsNotNone(session._cloud_task)
        self.assertEqual(len(scheduled), 1)
        # prevent warnings
        try:
            scheduled[0].close()
        except Exception:
            pass

    def test_cloud_roundtrip_aborts_if_gate_not_opened(self):
        session = self._make_session()

        async def run():
            async def _timeout(awaitable, *args, **kwargs):
                try:
                    awaitable.close()
                except Exception:
                    pass
                raise asyncio.TimeoutError

            with mock.patch('simo.fleet.voice_assistant.asyncio.wait_for', side_effect=_timeout):
                await session._cloud_roundtrip_and_play(b'\x00\x00')

        async_to_sync(run)()
        self.assertFalse(session.awaiting_response)
