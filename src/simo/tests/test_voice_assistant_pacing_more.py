import asyncio
from unittest import mock

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase


class VoiceAssistantPacingMoreTests(SimpleTestCase):
    def _make_session(self):
        from simo.fleet.voice_assistant import VoiceAssistantSession

        class ConsumerStub:
            instance = None
            colonel = None

            async def send(self, *args, **kwargs):
                return None

            async def send_data(self, *_args, **_kwargs):
                return None

        def _discard_task(coro):
            try:
                coro.close()
            except Exception:
                pass
            return mock.Mock(done=lambda: False)

        with mock.patch('simo.fleet.voice_assistant.asyncio.create_task', side_effect=_discard_task):
            return VoiceAssistantSession(ConsumerStub())

    def test_send_pcm_frame_rejects_empty(self):
        session = self._make_session()
        session.c.send = mock.AsyncMock()

        async def run():
            return await session._send_pcm_frame(b'')

        self.assertFalse(async_to_sync(run)())
        session.c.send.assert_not_called()

    def test_send_pcm_frame_rejects_odd_length(self):
        session = self._make_session()
        session.c.send = mock.AsyncMock()

        async def run():
            return await session._send_pcm_frame(b'\x00')

        self.assertFalse(async_to_sync(run)())
        session.c.send.assert_not_called()

    def test_send_pcm_frame_returns_false_when_adpcm_encode_empty(self):
        session = self._make_session()
        session.c.send = mock.AsyncMock()

        async def run():
            with mock.patch('simo.fleet.voice_assistant.adpcm4.encode', autospec=True, return_value=b''):
                return await session._send_pcm_frame(b'\x00\x00')

        self.assertFalse(async_to_sync(run)())
        session.c.send.assert_not_called()

    def test_send_pcm_frames_returns_zero_for_empty_input(self):
        session = self._make_session()

        async def run():
            return await session._send_pcm_frames(b'')

        self.assertEqual(async_to_sync(run)(), (0, 0))

    def test_send_pcm_frames_prefill_only_no_sleep(self):
        session = self._make_session()
        session.PLAY_CHUNK_BYTES = 4
        session.PLAY_CHUNK_INTERVAL = 0.01
        session.TX_PACE_BIAS = 1.0
        session._tx_prefill_chunks = 10

        session._send_pcm_frame = mock.AsyncMock(return_value=True)
        session._reset_stream_throttle = mock.Mock()

        async def run():
            with mock.patch('simo.fleet.voice_assistant.asyncio.sleep', autospec=True) as sleep:
                res = await session._send_pcm_frames(b'\x00' * 8)  # 2 frames
            return res, sleep

        (sent, chunks), sleep = async_to_sync(run)()
        self.assertEqual((sent, chunks), (8, 2))
        sleep.assert_not_called()
        session._reset_stream_throttle.assert_called_once()

    def test_send_pcm_frames_calls_send_pcm_frame_for_prefill_and_play(self):
        session = self._make_session()
        session.PLAY_CHUNK_BYTES = 4
        session.PLAY_CHUNK_INTERVAL = 0.01
        session.TX_PACE_BIAS = 1.0
        session._tx_prefill_chunks = 2
        session._send_pcm_frame = mock.AsyncMock(return_value=True)
        session._reset_stream_throttle = mock.Mock()

        fake_mon = {'t': 0.0}

        async def fake_sleep(dt):
            fake_mon['t'] += dt
            return None

        def fake_monotonic():
            return fake_mon['t']

        async def run():
            with (
                mock.patch('simo.fleet.voice_assistant.time.monotonic', autospec=True, side_effect=fake_monotonic),
                mock.patch('simo.fleet.voice_assistant.asyncio.sleep', autospec=True, side_effect=fake_sleep),
            ):
                return await session._send_pcm_frames(b'\x00' * 12)  # 3 frames

        sent, chunks = async_to_sync(run)()
        self.assertEqual((sent, chunks), (12, 3))
        self.assertEqual(session._send_pcm_frame.call_count, 3)
        session._reset_stream_throttle.assert_called_once()

    def test_send_pcm_frames_stops_when_send_frame_fails(self):
        session = self._make_session()
        session.PLAY_CHUNK_BYTES = 4
        session._tx_prefill_chunks = 1
        session._send_pcm_frame = mock.AsyncMock(side_effect=[True, False])
        session._reset_stream_throttle = mock.Mock()

        async def run():
            return await session._send_pcm_frames(b'\x00' * 8)

        sent, chunks = async_to_sync(run)()
        self.assertEqual((sent, chunks), (4, 1))

    def test_send_pcm_frames_returns_on_cancelled_sleep(self):
        session = self._make_session()
        session.PLAY_CHUNK_BYTES = 4
        session.PLAY_CHUNK_INTERVAL = 0.01
        session.TX_PACE_BIAS = 1.0
        session._tx_prefill_chunks = 1
        session._send_pcm_frame = mock.AsyncMock(return_value=True)
        session._reset_stream_throttle = mock.Mock()

        async def cancel_sleep(_dt):
            raise asyncio.CancelledError

        async def run():
            with mock.patch('simo.fleet.voice_assistant.asyncio.sleep', autospec=True, side_effect=cancel_sleep):
                return await session._send_pcm_frames(b'\x00' * 12)  # prefill 1, then cancelled

        sent, chunks = async_to_sync(run)()
        self.assertEqual((sent, chunks), (4, 1))

    def test_start_followup_timer_cancels_existing_task(self):
        session = self._make_session()
        old = mock.Mock(done=lambda: False)
        session._followup_task = old

        async def run():
            with mock.patch('simo.fleet.voice_assistant.asyncio.create_task', autospec=True, return_value=mock.Mock()):
                await session._start_followup_timer()

        async_to_sync(run)()
        old.cancel.assert_called_once()

    def test_prewarm_on_first_audio_requests_cloud_start_once(self):
        session = self._make_session()
        session.mcp_token = None

        async def run():
            with (
                mock.patch.object(session, 'ensure_mcp_token', autospec=True) as ensure,
                mock.patch('simo.fleet.voice_assistant.asyncio.create_task', autospec=True) as create_task,
            ):
                await session.prewarm_on_first_audio()
                await session.prewarm_on_first_audio()
            return ensure, create_task

        ensure, create_task = async_to_sync(run)()
        ensure.assert_called_once()
        create_task.assert_called_once()
