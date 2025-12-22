import time
from unittest import mock

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase
from django.utils import timezone

from simo.fleet.models import Colonel

from .base import BaseSimoTransactionTestCase, mk_instance


class VoiceAssistantSessionBehaviorTests(BaseSimoTransactionTestCase):
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

    def test_open_as_winner_opens_cloud_gate(self):
        session = self._make_session()

        async def run():
            session._start_session_notified = True  # avoid spawning cloud task
            with mock.patch('simo.fleet.voice_assistant.VoiceAssistantSession._set_is_vo_active', autospec=True) as set_vo:
                await session.open_as_winner()
            self.assertTrue(session.active)
            self.assertTrue(session._cloud_gate.is_set())
            set_vo.assert_called_once()

        async_to_sync(run)()

    def test_finalizer_loop_triggers_finalize_on_inactivity(self):
        session = self._make_session()
        session.active = True
        session.awaiting_response = False
        session.playing = False
        session.capture_buf.extend(b'\x00\x00')

        now = time.time()
        session.last_chunk_ts = now - (session.INACTIVITY_MS / 1000.0) - 0.2

        async def run():
            with mock.patch('simo.fleet.voice_assistant.time.time', autospec=True, return_value=now), \
                    mock.patch('simo.fleet.voice_assistant.asyncio.sleep', autospec=True), \
                    mock.patch('simo.fleet.voice_assistant.VoiceAssistantSession._finalize_utterance', autospec=True) as fin:
                await session._finalizer_loop()
            fin.assert_called_once()

        async_to_sync(run)()


class VoiceAssistantArbitratorTests(BaseSimoTransactionTestCase):
    def _mk_consumer(self, instance, colonel):
        class Consumer:
            def __init__(self, instance, colonel):
                self.instance = instance
                self.colonel = colonel

        return Consumer(instance, colonel)

    def test_busy_rejects_when_other_active(self):
        from simo.fleet.voice_assistant import VoiceAssistantArbitrator

        inst = mk_instance('inst-a', 'A')
        c1 = Colonel.objects.create(instance=inst, uid='c-1', name='C1')
        other = Colonel.objects.create(
            instance=inst,
            uid='c-2',
            name='C2',
        )
        Colonel.objects.filter(id=other.id).update(
            socket_connected=True,
            is_vo_active=True,
            last_wake=timezone.now(),
        )

        session = mock.AsyncMock()
        arb = VoiceAssistantArbitrator(self._mk_consumer(inst, c1), session)

        async_to_sync(arb._decide_arbitration)()

        session.reject_busy.assert_awaited()
        session.open_as_winner.assert_not_awaited()

    def test_no_candidates_opens_as_winner(self):
        from simo.fleet.voice_assistant import VoiceAssistantArbitrator

        inst = mk_instance('inst-a', 'A')
        c1 = Colonel.objects.create(instance=inst, uid='c-1', name='C1')

        session = mock.AsyncMock()
        arb = VoiceAssistantArbitrator(self._mk_consumer(inst, c1), session)

        # No last_wake set for anyone => candidate list is empty.
        async_to_sync(arb._decide_arbitration)()

        session.open_as_winner.assert_awaited()

    def test_candidate_ranking_promotes_self_and_opens(self):
        from simo.fleet.voice_assistant import VoiceAssistantArbitrator

        inst = mk_instance('inst-a', 'A')
        now = timezone.now()
        c1 = Colonel.objects.create(
            instance=inst,
            uid='c-1',
            name='C1',
            last_wake=now,
            wake_stats={'avg2p5_s': 10},
        )
        Colonel.objects.create(
            instance=inst,
            uid='c-2',
            name='C2',
            last_wake=now,
            wake_stats={'avg2p5_s': 1},
        )

        session = mock.AsyncMock()
        arb = VoiceAssistantArbitrator(self._mk_consumer(inst, c1), session)

        async_to_sync(arb._decide_arbitration)()

        c1.refresh_from_db()
        self.assertTrue(c1.is_vo_active)
        session.open_as_winner.assert_awaited()

    def test_other_candidate_becomes_active_rejects_busy(self):
        from simo.fleet.voice_assistant import VoiceAssistantArbitrator
        import simo.fleet.voice_assistant as va

        inst = mk_instance('inst-a', 'A')
        now = timezone.now()

        c1 = Colonel.objects.create(instance=inst, uid='c-1', name='C1')
        c2 = Colonel.objects.create(instance=inst, uid='c-2', name='C2')
        Colonel.objects.filter(id=c1.id).update(last_wake=now, wake_stats={'avg2p5_s': 1})
        Colonel.objects.filter(id=c2.id).update(last_wake=now, wake_stats={'avg2p5_s': 10})

        session = mock.AsyncMock()
        arb = VoiceAssistantArbitrator(self._mk_consumer(inst, c1), session)

        orig_sync_to_async = va.sync_to_async

        def patched_sync_to_async(func, *args, **kwargs):
            # Force chosen to appear active during confirm-grace loop.
            if getattr(func, '__name__', '') == '_chosen_active':
                async def _ret_true():
                    return True

                return _ret_true
            if getattr(func, '__name__', '') == '_any_other_active':
                async def _ret_false():
                    return False

                return _ret_false
            return orig_sync_to_async(func, *args, **kwargs)

        async def run():
            with mock.patch('simo.fleet.voice_assistant.sync_to_async', side_effect=patched_sync_to_async), \
                    mock.patch('simo.fleet.voice_assistant.asyncio.sleep', new=mock.AsyncMock()):
                await arb._decide_arbitration()

        async_to_sync(run)()
        session.reject_busy.assert_awaited()
        session.open_as_winner.assert_not_awaited()

    def test_other_candidate_never_active_fallback_promotes_self(self):
        from simo.fleet.voice_assistant import VoiceAssistantArbitrator

        inst = mk_instance('inst-a', 'A')
        now = timezone.now()
        c1 = Colonel.objects.create(instance=inst, uid='c-1', name='C1')
        c2 = Colonel.objects.create(instance=inst, uid='c-2', name='C2')
        Colonel.objects.filter(id=c1.id).update(last_wake=now, wake_stats={'avg2p5_s': 1})
        Colonel.objects.filter(id=c2.id).update(last_wake=now, wake_stats={'avg2p5_s': 10})

        session = mock.AsyncMock()
        arb = VoiceAssistantArbitrator(self._mk_consumer(inst, c1), session)
        arb.WINNER_CONFIRM_GRACE_MS = 0

        async_to_sync(arb._decide_arbitration)()
        c1.refresh_from_db()
        self.assertTrue(c1.is_vo_active)
        session.open_as_winner.assert_awaited()


class VoiceAssistantFollowupTimerTests(SimpleTestCase):
    def _make_session(self):
        from simo.fleet.voice_assistant import VoiceAssistantSession

        class ConsumerStub:
            instance = None
            colonel = None

            async def send_data(self, data):
                return None

        def _discard_task(coro):
            try:
                coro.close()
            except Exception:
                pass
            return mock.Mock()

        with mock.patch('simo.fleet.voice_assistant.asyncio.create_task', side_effect=_discard_task):
            return VoiceAssistantSession(ConsumerStub())

    def test_followup_timer_ends_session_when_idle(self):
        session = self._make_session()
        session.active = True
        session.playing = False
        session.awaiting_response = False
        session.capture_buf.clear()

        captured = []

        def _capture_task(coro):
            captured.append(coro)
            return mock.Mock(done=lambda: False, cancel=lambda: None)

        async def run():
            with mock.patch('simo.fleet.voice_assistant.asyncio.create_task', side_effect=_capture_task):
                await session._start_followup_timer()

        async_to_sync(run)()
        self.assertEqual(len(captured), 1)

        async def run_timer():
            with mock.patch('simo.fleet.voice_assistant.asyncio.sleep', new=mock.AsyncMock()), \
                    mock.patch('simo.fleet.voice_assistant.VoiceAssistantSession._end_session', new=mock.AsyncMock()) as end:
                await captured[0]
                end.assert_awaited_with(cloud_also=False)

        async_to_sync(run_timer)()

    def test_followup_timer_does_not_end_when_buffer_nonempty(self):
        session = self._make_session()
        session.active = True
        session.playing = False
        session.awaiting_response = False
        session.capture_buf.extend(b'\x00\x00')

        captured = []

        def _capture_task(coro):
            captured.append(coro)
            return mock.Mock(done=lambda: False, cancel=lambda: None)

        async def run():
            with mock.patch('simo.fleet.voice_assistant.asyncio.create_task', side_effect=_capture_task):
                await session._start_followup_timer()

        async_to_sync(run)()

        async def run_timer():
            with mock.patch('simo.fleet.voice_assistant.asyncio.sleep', new=mock.AsyncMock()), \
                    mock.patch('simo.fleet.voice_assistant.VoiceAssistantSession._end_session', new=mock.AsyncMock()) as end:
                await captured[0]
                end.assert_not_awaited()

        async_to_sync(run_timer)()
