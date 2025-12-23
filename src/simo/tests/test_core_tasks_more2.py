from __future__ import annotations

import datetime
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone


class TestRestartAndRebootTasks(SimpleTestCase):
    def test_supervisor_restart_runs_expected_commands(self):
        from simo.core.tasks import supervisor_restart

        with (
            mock.patch('simo.core.tasks.time.sleep', autospec=True),
            mock.patch('simo.core.tasks.subprocess.run', autospec=True) as run,
        ):
            supervisor_restart()

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], ['redis-cli', 'flushall'])
        self.assertEqual(run.call_args_list[1].args[0], ['supervisorctl', 'restart', 'all'])

    def test_hardware_reboot_runs_reboot(self):
        from simo.core.tasks import hardware_reboot

        with (
            mock.patch('simo.core.tasks.time.sleep', autospec=True),
            mock.patch('simo.core.tasks.subprocess.run', autospec=True) as run,
            mock.patch('builtins.print') as printer,
        ):
            hardware_reboot()

        printer.assert_called()
        run.assert_called_once_with(['reboot'])


class TestVacuumTasks(SimpleTestCase):
    def test_vacuum_executes_for_each_table(self):
        from simo.core.tasks import VACUUM_SQL, vacuum

        cursor = mock.Mock()
        cursor.fetchall.return_value = [('public', 't1'), ('public', 't2')]
        conn = mock.Mock()
        conn.cursor.return_value = cursor

        with mock.patch('django.db.connection', conn):
            vacuum.run()

        cursor.execute.assert_any_call(VACUUM_SQL)
        self.assertIn('VACUUM "public"."t1";', [c.args[0] for c in cursor.execute.call_args_list])
        self.assertIn('VACUUM "public"."t2";', [c.args[0] for c in cursor.execute.call_args_list])

    def test_vacuum_full_executes_for_each_table(self):
        from simo.core.tasks import VACUUM_SQL, vacuum_full

        cursor = mock.Mock()
        cursor.fetchall.return_value = [('public', 't1')]
        conn = mock.Mock()
        conn.cursor.return_value = cursor

        with mock.patch('django.db.connection', conn):
            vacuum_full.run()

        cursor.execute.assert_any_call(VACUUM_SQL)
        self.assertIn('VACUUM FULL "public"."t1";', [c.args[0] for c in cursor.execute.call_args_list])


class TestMaybeUpdateToLatestMore(SimpleTestCase):
    def test_bad_response_returns_none(self):
        from simo.core.tasks import maybe_update_to_latest

        resp = mock.Mock(status_code=500)
        with (
            mock.patch('simo.core.tasks.requests.get', return_value=resp),
            mock.patch('builtins.print') as printer,
        ):
            out = maybe_update_to_latest()

        self.assertIsNone(out)
        printer.assert_called()

    def test_up_to_date_returns_none(self):
        from simo.core.tasks import maybe_update_to_latest

        ds = {'core__latest_version_available': '', 'core__auto_update': False}
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {'releases': {'1.2.3': {}, '1.2.2': {}}}

        with (
            mock.patch('simo.core.tasks.requests.get', return_value=resp),
            mock.patch('simo.conf.dynamic_settings', ds),
            mock.patch('simo.core.tasks.pkg_resources.get_distribution', return_value=mock.Mock(version='1.2.3')),
        ):
            out = maybe_update_to_latest()

        self.assertIsNone(out)
        self.assertEqual(ds['core__latest_version_available'], '1.2.3')

    def test_auto_update_disabled_and_instances_exist_returns_none(self):
        from simo.core.tasks import maybe_update_to_latest

        ds = {'core__latest_version_available': '', 'core__auto_update': False}
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {'releases': {'1.0.1': {}, '1.0.0': {}}}

        inst_qs = mock.Mock()
        inst_qs.count.return_value = 1

        with (
            mock.patch('simo.core.tasks.requests.get', return_value=resp),
            mock.patch('simo.conf.dynamic_settings', ds),
            mock.patch('simo.core.tasks.pkg_resources.get_distribution', return_value=mock.Mock(version='1.0.0')),
            mock.patch('simo.core.models.Instance.objects.all', return_value=inst_qs),
            mock.patch('builtins.print') as printer,
        ):
            out = maybe_update_to_latest()

        self.assertIsNone(out)
        printer.assert_called()


class TestSetupPeriodicTasks(SimpleTestCase):
    def test_setup_periodic_tasks_registers_expected_intervals(self):
        from simo.core.tasks import setup_periodic_tasks

        sender = mock.Mock()
        setup_periodic_tasks(sender)

        # 4 periodic tasks expected
        self.assertEqual(sender.add_periodic_task.call_count, 4)
        intervals = [c.args[0] for c in sender.add_periodic_task.call_args_list]
        self.assertIn(20, intervals)
        self.assertIn(60, intervals)
        self.assertIn(60 * 60, intervals)


class TestClearHistoryTask(SimpleTestCase):
    def test_clear_history_deletes_old_and_trims_excess(self):
        from simo.core import tasks

        inst = mock.Mock()
        inst.id = 1
        inst.history_days = 90

        ch_qs_old = mock.Mock()
        ch_qs_old.delete = mock.Mock()
        ch_qs_all = mock.Mock()
        ch_qs_all.order_by.return_value.values.return_value.iterator.return_value = [
            {'id': i} for i in range(0, 5002)
        ]
        ch_qs_trim = mock.Mock()
        ch_qs_trim.delete = mock.Mock()

        ha_qs_old = mock.Mock()
        ha_qs_old.delete = mock.Mock()
        ha_qs_all = mock.Mock()
        ha_qs_all.order_by.return_value.values.return_value.iterator.return_value = [
            {'id': i} for i in range(0, 1002)
        ]
        ha_qs_trim = mock.Mock()
        ha_qs_trim.delete = mock.Mock()

        act_qs_old = mock.Mock()
        act_qs_old.delete = mock.Mock()
        act_qs_all = mock.Mock()
        act_qs_all.order_by.return_value.values.return_value.iterator.return_value = [
            {'id': i} for i in range(0, 5002)
        ]
        act_qs_trim = mock.Mock()
        act_qs_trim.delete = mock.Mock()

        def ch_filter_side_effect(*_args, **kwargs):
            if kwargs.get('date__lt') is not None:
                return ch_qs_old
            if kwargs.get('id__in') is not None:
                return ch_qs_trim
            return ch_qs_all

        def ha_filter_side_effect(*_args, **kwargs):
            if kwargs.get('start__lt') is not None:
                return ha_qs_old
            if kwargs.get('id__in') is not None:
                return ha_qs_trim
            return ha_qs_all

        def act_filter_side_effect(*_args, **kwargs):
            if kwargs.get('timestamp__lt') is not None:
                return act_qs_old
            if kwargs.get('id__in') is not None:
                return act_qs_trim
            return act_qs_all

        with (
            mock.patch.object(tasks.Instance.objects, 'all', return_value=[inst]),
            mock.patch.object(tasks, 'introduce_instance', autospec=True),
            mock.patch.object(tasks.ComponentHistory.objects, 'filter', side_effect=ch_filter_side_effect),
            mock.patch.object(tasks.HistoryAggregate.objects, 'filter', side_effect=ha_filter_side_effect),
            mock.patch.object(tasks.Action.objects, 'filter', side_effect=act_filter_side_effect),
            mock.patch('simo.core.tasks.timezone.now', return_value=timezone.now()),
            mock.patch('builtins.print'),
        ):
            tasks.clear_history()

        ch_qs_old.delete.assert_called_once()
        ha_qs_old.delete.assert_called_once()
        act_qs_old.delete.assert_called_once()

        # Should delete items beyond keep window.
        ch_qs_trim.delete.assert_called_once()
        ha_qs_trim.delete.assert_called_once()
        act_qs_trim.delete.assert_called_once()
