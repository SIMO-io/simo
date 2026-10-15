import threading
from itertools import product
from unittest import mock

from django.test import SimpleTestCase

from simo.generic.gateways import GenericGatewayHandler


class GenericGatewayPulseConcurrencyTests(SimpleTestCase):
    def setUp(self):
        self.reset_handler()
        self.pulse = {'frame': 1, 'duty': 0.5}

    def reset_handler(self):
        self.handler = GenericGatewayHandler.__new__(GenericGatewayHandler)
        self.handler.pulsing_switches = {}
        self.handler._pulse_lock = threading.Lock()
        self.handler._pulse_worker = None
        self.handler.logger = mock.Mock()

    def component(self, component_id=1, pulse=None):
        comp = mock.Mock(id=component_id)
        comp.meta = {'pulse': dict(pulse or self.pulse)}
        return comp

    def register(self, comp):
        with mock.patch('simo.generic.gateways.time.time', return_value=0):
            self.handler.start_pulse(comp, comp.meta['pulse'])
        return self.handler._pulse_snapshot()[comp.id]

    def race(self, operation, blocked_io, concurrent):
        """Pause worker I/O while a second thread changes pulse registration."""
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def block(*_args, **_kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError('Concurrent registration blocked by pulse I/O')

        def run():
            try:
                operation()
            except BaseException as error:
                errors.append(error)

        blocked_io.side_effect = block
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(3), 'Worker did not reach I/O')
            concurrent()
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        if errors:
            raise errors[0]

    def test_registration_during_iteration_does_not_resize_live_iterator(self):
        first = self.component()
        second = self.component(2)
        self.register(first)
        self.register(second)
        third = self.component(3)
        first.meta = {}
        snapshot = self.handler._pulse_snapshot()

        def iterate():
            for component_id, data in snapshot.items():
                self.handler._watch_switch_pulse(component_id, data)

        with mock.patch('simo.generic.gateways.time.time', return_value=2):
            self.race(iterate, first.refresh_from_db,
                      lambda: self.handler.start_pulse(third, self.pulse))

        self.assertEqual(set(self.handler._pulse_snapshot()), {2, 3})
        second.send.assert_called_with(False)

    def test_refresh_cannot_overwrite_or_remove_concurrent_update(self):
        for stale_pulse in (None, {'frame': 3, 'duty': 0.2}):
            with self.subTest(stale_pulse=stale_pulse):
                self.reset_handler()
                comp = self.component()
                data = self.register(comp)
                comp.meta = {'pulse': stale_pulse}
                new_comp = self.component(pulse={'frame': 10, 'duty': 0.7})
                with mock.patch('simo.generic.gateways.time.time', return_value=2):
                    self.race(
                        lambda: self.handler._watch_switch_pulse(comp.id, data),
                        comp.refresh_from_db,
                        lambda: self.handler.start_pulse(new_comp, new_comp.meta['pulse']),
                    )
                current = self.handler._pulse_snapshot()[comp.id]
                self.assertEqual(current['pulse'], new_comp.meta['pulse'])
                self.assertIs(current['comp'], new_comp)
                self.assertTrue(current['value'])
                self.assertEqual(current['last_toggle'], 0)

    def test_publish_completion_cannot_overwrite_concurrent_update(self):
        comp = self.component()
        data = self.register(comp)
        new_pulse = {'frame': 10, 'duty': 0.7}
        with mock.patch('simo.generic.gateways.time.time', return_value=2):
            self.race(
                lambda: self.handler._watch_switch_pulse(comp.id, data),
                comp.send,
                lambda: self.handler.start_pulse(comp, new_pulse),
            )
        current = self.handler._pulse_snapshot()[comp.id]
        self.assertEqual(current['pulse'], new_pulse)
        self.assertTrue(current['value'])
        self.assertEqual(current['last_toggle'], 0)

    def test_resync_cannot_overwrite_or_remove_concurrent_update(self):
        for found_in_db, tracked in product((False, True), repeat=2):
            with self.subTest(found_in_db=found_in_db, tracked=tracked):
                self.reset_handler()
                comp = self.component()
                if tracked:
                    self.register(comp)
                queried = threading.Event()
                resume = threading.Event()
                errors = []
                new_pulse = {'frame': 10, 'duty': 0.7}

                def query(**_kwargs):
                    queried.set()
                    if not resume.wait(3):
                        raise AssertionError('DB query held the pulse lock')
                    return [comp] if found_in_db else []

                def sync():
                    try:
                        self.handler._sync_switch_pulses()
                    except BaseException as error:
                        errors.append(error)

                with mock.patch('simo.generic.gateways.Component.objects.filter', side_effect=query):
                    worker = threading.Thread(target=sync, daemon=True)
                    worker.start()
                    try:
                        self.assertTrue(queried.wait(3))
                        self.handler.start_pulse(comp, new_pulse)
                        self.handler.start_pulse(self.component(2), new_pulse)
                    finally:
                        resume.set()
                        worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                snapshot = self.handler._pulse_snapshot()
                self.assertEqual(set(snapshot), {1, 2})
                self.assertEqual(snapshot[1]['pulse'], new_pulse)
                self.assertEqual(snapshot[2]['pulse'], new_pulse)

    def test_worker_retries_failed_switch_and_keeps_processing_others(self):
        first = self.component()
        second = self.component(2)
        self.register(first)
        self.register(second)
        first.send.reset_mock()
        first.send.side_effect = [RuntimeError('publish failed'), None]
        exit_event = threading.Event()
        ticks = 0

        def tick(_seconds):
            nonlocal ticks
            ticks += 1
            if ticks == 2:
                exit_event.set()

        with (
            mock.patch.object(self.handler, '_sync_switch_pulses'),
            mock.patch('simo.generic.gateways.time.sleep', side_effect=tick),
            mock.patch('simo.generic.gateways.time.time', return_value=2),
        ):
            self.handler.watch_switch_pulses(exit_event)

        self.assertEqual(first.send.call_args_list, [mock.call(False), mock.call(False)])
        second.send.assert_called_with(False)
        self.assertFalse(self.handler._pulse_snapshot()[first.id]['value'])
        self.handler.logger.exception.assert_called_once()

    def test_failed_initial_send_is_retried_by_worker(self):
        comp = self.component()
        comp.send.side_effect = [RuntimeError('publish failed'), None]
        with self.assertRaises(RuntimeError):
            self.register(comp)
        data = self.handler._pulse_snapshot()[comp.id]
        self.assertIsNone(data['value'])
        self.handler._watch_switch_pulse(comp.id, data)
        self.assertTrue(self.handler._pulse_snapshot()[comp.id]['value'])
        self.assertEqual(comp.send.call_args_list, [mock.call(True), mock.call(True)])

    def test_supervisor_restarts_worker_after_error_or_unexpected_return(self):
        for failure in (RuntimeError('DB unavailable'), None):
            with self.subTest(failure=failure):
                self.reset_handler()
                exit_event = threading.Event()

                def recovered(_exit):
                    exit_event.set()

                with mock.patch.object(
                    self.handler, 'watch_switch_pulses', side_effect=[failure, None]
                ) as watch:
                    self.handler._ensure_pulse_worker(exit_event)
                    self.handler._pulse_worker.join(3)
                    self.assertFalse(self.handler._pulse_worker.is_alive())
                    watch.side_effect = recovered
                    self.handler._ensure_pulse_worker(exit_event)
                    self.handler._pulse_worker.join(3)
                    self.assertTrue(exit_event.is_set())
                    self.assertEqual(watch.call_count, 2)
                    self.handler._ensure_pulse_worker(exit_event)
                    self.assertEqual(watch.call_count, 2)
                self.handler.logger.error.assert_called_once()
                self.assertEqual(self.handler.logger.exception.call_count, int(failure is not None))
