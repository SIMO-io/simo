import asyncio
from types import SimpleNamespace
from unittest import mock

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase


class VoiceAssistantInternalsMoreTests(SimpleTestCase):
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
            return mock.Mock()

        with mock.patch('simo.fleet.voice_assistant.asyncio.create_task', side_effect=_discard_task):
            return VoiceAssistantSession(ConsumerStub())

    def test_normalize_language_returns_none_for_empty(self):
        from simo.fleet.voice_assistant import _normalize_language

        self.assertIsNone(_normalize_language(None))
        self.assertIsNone(_normalize_language(''))
        self.assertIsNone(_normalize_language('   '))

    def test_normalize_language_keeps_iso_639_1_lowercase(self):
        from simo.fleet.voice_assistant import _normalize_language

        self.assertEqual(_normalize_language('EN'), 'en')

    def test_normalize_language_strips_region_and_underscores(self):
        from simo.fleet.voice_assistant import _normalize_language

        self.assertEqual(_normalize_language('lt-LT'), 'lt')
        self.assertEqual(_normalize_language('lt_LT'), 'lt')

    def test_normalize_language_parses_accept_language_header(self):
        from simo.fleet.voice_assistant import _normalize_language

        self.assertEqual(_normalize_language('lt-LT,lt;q=0.9'), 'lt')

    def test_encode_mp3_uses_pydub_when_lameenc_missing(self):
        session = self._make_session()

        class InlineLoop:
            async def run_in_executor(self, _executor, func):
                return func()

        async def run():
            with (
                mock.patch('simo.fleet.voice_assistant.lameenc', None),
                mock.patch.object(session, '_encode_mp3_pydub', autospec=True, return_value=b'mp3'),
                mock.patch('simo.fleet.voice_assistant.asyncio.get_running_loop', return_value=InlineLoop()),
            ):
                return await session._encode_mp3(b'pcm')

        res = async_to_sync(run)()
        self.assertEqual(res, b'mp3')

    def test_encode_mp3_uses_lameenc_when_available(self):
        session = self._make_session()

        class Encoder:
            def set_bit_rate(self, *_a):
                return None

            def set_in_sample_rate(self, *_a):
                return None

            def set_channels(self, *_a):
                return None

            def set_quality(self, *_a):
                return None

            def encode(self, _pcm):
                return b'a'

            def flush(self):
                return b'b'

        fake_lame = SimpleNamespace(Encoder=Encoder)

        class InlineLoop:
            async def run_in_executor(self, _executor, func):
                return func()

        async def run():
            with (
                mock.patch('simo.fleet.voice_assistant.lameenc', fake_lame),
                mock.patch('simo.fleet.voice_assistant.asyncio.get_running_loop', return_value=InlineLoop()),
            ):
                return await session._encode_mp3(b'pcm')

        res = async_to_sync(run)()
        self.assertEqual(res, b'ab')

    def test_encode_mp3_falls_back_to_pydub_on_lameenc_error(self):
        session = self._make_session()

        class Encoder:
            def set_bit_rate(self, *_a):
                return None

            def set_in_sample_rate(self, *_a):
                return None

            def set_channels(self, *_a):
                return None

            def set_quality(self, *_a):
                return None

            def encode(self, _pcm):
                raise RuntimeError('boom')

            def flush(self):
                return b''

        fake_lame = SimpleNamespace(Encoder=Encoder)

        class InlineLoop:
            async def run_in_executor(self, _executor, func):
                return func()

        async def run():
            with (
                mock.patch('simo.fleet.voice_assistant.lameenc', fake_lame),
                mock.patch.object(session, '_encode_mp3_pydub', autospec=True, return_value=b'fallback'),
                mock.patch('simo.fleet.voice_assistant.asyncio.get_running_loop', return_value=InlineLoop()),
            ):
                return await session._encode_mp3(b'pcm')

        res = async_to_sync(run)()
        self.assertEqual(res, b'fallback')

    def test_encode_mp3_pydub_returns_none_when_audiosegment_missing(self):
        session = self._make_session()
        with mock.patch('simo.fleet.voice_assistant.AudioSegment', None):
            self.assertIsNone(session._encode_mp3_pydub(b'pcm'))

    def test_decode_mp3_returns_none_when_audiosegment_missing(self):
        session = self._make_session()
        async def run():
            with mock.patch('simo.fleet.voice_assistant.AudioSegment', None):
                return await session._decode_mp3(b'mp3')
        self.assertIsNone(async_to_sync(run)())

    def test_decode_opus_stream_returns_empty_for_empty_input(self):
        session = self._make_session()

        async def run():
            return await session._decode_opus_stream(b'')

        self.assertEqual(async_to_sync(run)(), b'')

    def test_decode_opus_stream_returns_none_when_ffmpeg_fails_to_start(self):
        session = self._make_session()

        async def run():
            with mock.patch('simo.fleet.voice_assistant.asyncio.create_subprocess_exec', side_effect=OSError('no ffmpeg')):
                return await session._decode_opus_stream(b'123')

        self.assertIsNone(async_to_sync(run)())

    def test_decode_opus_stream_returns_none_on_nonzero_exit(self):
        session = self._make_session()

        class Proc:
            returncode = 1

            async def communicate(self, _data):
                return b'', b'error'

        async def run():
            with mock.patch('simo.fleet.voice_assistant.asyncio.create_subprocess_exec', autospec=True, return_value=Proc()):
                return await session._decode_opus_stream(b'123')

        self.assertIsNone(async_to_sync(run)())

    def test_decode_opus_stream_returns_stdout_on_success(self):
        session = self._make_session()

        class Proc:
            returncode = 0

            async def communicate(self, _data):
                return b'pcm', b''

        async def run():
            with mock.patch('simo.fleet.voice_assistant.asyncio.create_subprocess_exec', autospec=True, return_value=Proc()):
                return await session._decode_opus_stream(b'123')

        self.assertEqual(async_to_sync(run)(), b'pcm')

    def test_send_pcm_frame_builds_adpcm_packet(self):
        session = self._make_session()
        session.c.send = mock.AsyncMock()
        session._tx_adpcm_state.predictor = -10
        session._tx_adpcm_state.index = 5

        from simo.fleet.voice_assistant import ADPCM_FRAME_FLAG, SPK_CHANNEL_ID

        async def run():
            with mock.patch('simo.fleet.voice_assistant.adpcm4.encode', autospec=True, return_value=b'\x01\x02'):
                return await session._send_pcm_frame(b'\x00\x00\x00\x00')

        ok = async_to_sync(run)()
        self.assertTrue(ok)
        sent = session.c.send.call_args.kwargs['bytes_data']
        self.assertEqual(sent[0], SPK_CHANNEL_ID | ADPCM_FRAME_FLAG)
        # 4 bytes -> 2 samples
        self.assertEqual(sent[1], 2)
        self.assertEqual(sent[2], 0)
        # predictor=-10 -> 0xFFF6
        self.assertEqual(sent[3], 0xF6)
        self.assertEqual(sent[4], 0xFF)
        self.assertEqual(sent[5], 5)
