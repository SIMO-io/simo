import datetime
from unittest import mock

import pytz
from django.utils import timezone

from .base import BaseSimoTestCase, mk_instance


class UsersTasksTests(BaseSimoTestCase):
    def test_clear_device_report_logs_deletes_only_older_than_retention(self):
        from simo.users.models import UserDevice, UserDeviceReportLog
        from simo.users.tasks import clear_device_report_logs

        inst0 = mk_instance('inst-a', 'A')
        inst0.device_report_history_days = 0
        inst0.save(update_fields=['device_report_history_days'])

        inst5 = mk_instance('inst-b', 'B')
        inst5.device_report_history_days = 5
        inst5.save(update_fields=['device_report_history_days'])

        dev = UserDevice.objects.create(os='ios', token='tok1', is_primary=True)

        now = timezone.make_aware(datetime.datetime(2024, 1, 10, 12, 0, 0), timezone=pytz.utc)

        # inst0 retention: now - 1 hour
        log0_old = UserDeviceReportLog.objects.create(user_device=dev, instance=inst0)
        log0_new = UserDeviceReportLog.objects.create(user_device=dev, instance=inst0)
        UserDeviceReportLog.objects.filter(pk=log0_old.pk).update(datetime=now - datetime.timedelta(hours=2))
        UserDeviceReportLog.objects.filter(pk=log0_new.pk).update(datetime=now - datetime.timedelta(minutes=30))

        # inst5 retention: now - 5 days - 1 hour
        log5_old = UserDeviceReportLog.objects.create(user_device=dev, instance=inst5)
        log5_new = UserDeviceReportLog.objects.create(user_device=dev, instance=inst5)
        UserDeviceReportLog.objects.filter(pk=log5_old.pk).update(datetime=now - datetime.timedelta(days=6))
        UserDeviceReportLog.objects.filter(pk=log5_new.pk).update(datetime=now - datetime.timedelta(days=4))

        with mock.patch('simo.users.tasks.timezone.now', autospec=True, return_value=now):
            clear_device_report_logs()

        remaining = set(UserDeviceReportLog.objects.values_list('pk', flat=True))
        self.assertIn(log0_new.pk, remaining)
        self.assertNotIn(log0_old.pk, remaining)
        self.assertIn(log5_new.pk, remaining)
        self.assertNotIn(log5_old.pk, remaining)

    def test_rebuild_mqtt_acls_runs_once_when_flag_is_set(self):
        from simo.users.tasks import rebuild_mqtt_acls
        import simo.users.utils as users_utils

        ds = {'core__needs_mqtt_acls_rebuild': True}
        users_utils.update_mqtt_acls.reset_mock()
        with mock.patch('simo.conf.dynamic_settings', ds):
            rebuild_mqtt_acls()

        self.assertFalse(ds['core__needs_mqtt_acls_rebuild'])
        users_utils.update_mqtt_acls.assert_called_once()

    def test_rebuild_mqtt_acls_noop_when_flag_is_not_set(self):
        from simo.users.tasks import rebuild_mqtt_acls
        import simo.users.utils as users_utils

        ds = {'core__needs_mqtt_acls_rebuild': False}
        users_utils.update_mqtt_acls.reset_mock()
        with mock.patch('simo.conf.dynamic_settings', ds):
            rebuild_mqtt_acls()

        users_utils.update_mqtt_acls.assert_not_called()

    def test_setup_periodic_tasks_registers_expected_schedules(self):
        import simo.users.tasks as tasks

        sender = mock.Mock()
        with (
            mock.patch.object(tasks.clear_device_report_logs, 's', autospec=True, return_value='sig1'),
            mock.patch.object(tasks.rebuild_mqtt_acls, 's', autospec=True, return_value='sig2'),
        ):
            tasks.setup_periodic_tasks(sender)

        sender.add_periodic_task.assert_any_call(60 * 60, 'sig1')
        sender.add_periodic_task.assert_any_call(30, 'sig2')
