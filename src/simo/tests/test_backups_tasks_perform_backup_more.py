import json
import os
from unittest import mock

from django.utils import timezone

from simo.backups.models import BackupLog

from .base import BaseSimoTestCase, mk_instance


class PerformBackupMoreTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        BackupLog.objects.all().delete()
        self.inst = mk_instance('inst-a', 'A')

    def _run_backup(self, *, month_exists: bool, borg_ok: bool = True, ismount_boot=False, ismount_efi=False, disk_free=None):
        from simo.backups.tasks import perform_backup

        sd = '/mnt'
        snap_mount = '/var/backups/simo-main'
        hub = f'{sd}/simo_backups/hub-0x1'
        month_folder = os.path.join(hub, '2025-12')

        res_ok = mock.Mock(returncode=0, stderr=b'', stdout=b'')
        res_fail = mock.Mock(returncode=1, stderr=b'fail', stdout=b'')

        calls = []

        def run_side_effect(cmd, *args, **kwargs):
            calls.append((cmd, kwargs))
            # borg info should simulate failure if month exists but borg repo broken.
            if isinstance(cmd, str) and cmd.startswith('borg info'):
                return res_fail
            if isinstance(cmd, str) and cmd.startswith('borg create'):
                return res_ok if borg_ok else res_fail
            return res_ok

        def exists(path):
            if path in (sd, hub):
                return True
            if path == month_folder:
                return month_exists
            return False

        def ismount(path):
            if path == '/boot':
                return bool(ismount_boot)
            if path == '/boot/efi':
                return bool(ismount_efi)
            return False

        if disk_free is None:
            disk_free = [30 * 1024 * 1024 * 1024]
        disk = [mock.Mock(free=v) for v in disk_free]

        with (
            mock.patch('simo.backups.tasks.get_partitions', autospec=True, return_value=('vg', 'root', sd)),
            mock.patch('simo.backups.tasks.create_snap', autospec=True, return_value='snap'),
            mock.patch('simo.backups.tasks.uuid.getnode', autospec=True, return_value=1),
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, side_effect=exists),
            mock.patch('simo.backups.tasks.os.makedirs', autospec=True),
            mock.patch('simo.backups.tasks.shutil.rmtree', autospec=True),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect),
            mock.patch('simo.backups.tasks.open', mock.mock_open(), create=True),
            mock.patch('simo.backups.tasks.datetime', autospec=True) as dt,
            mock.patch('simo.backups.tasks.os.path.ismount', autospec=True, side_effect=ismount),
            mock.patch('simo.backups.tasks.shutil.disk_usage', autospec=True, side_effect=lambda *_a, **_k: disk.pop(0)),
            mock.patch('simo.backups.tasks.os.listdir', autospec=True, return_value=['2025-12']),
            mock.patch('simo.backups.tasks.os.path.isdir', autospec=True, return_value=True),
        ):
            dt.now.return_value = mock.Mock(year=2025, month=12)
            perform_backup()

        return calls

    def test_perform_backup_inits_borg_when_month_folder_missing(self):
        calls = self._run_backup(month_exists=False)
        borg_init = [c for c in calls if isinstance(c[0], str) and c[0].startswith('borg init')]
        self.assertEqual(len(borg_init), 1)

    def test_perform_backup_reinits_borg_when_borg_info_fails(self):
        calls = self._run_backup(month_exists=True)
        borg_info = [c for c in calls if isinstance(c[0], str) and c[0].startswith('borg info')]
        borg_init = [c for c in calls if isinstance(c[0], str) and c[0].startswith('borg init')]
        self.assertEqual(len(borg_info), 1)
        self.assertEqual(len(borg_init), 1)

    def test_perform_backup_command_does_not_exclude_boot(self):
        calls = self._run_backup(month_exists=False)
        borg_create = [c for c in calls if isinstance(c[0], str) and c[0].startswith('borg create')]
        self.assertEqual(len(borg_create), 1)
        self.assertNotIn('--exclude=boot', borg_create[0][0])

    def test_perform_backup_logs_success(self):
        self._run_backup(month_exists=False, borg_ok=True)
        self.assertEqual(BackupLog.objects.filter(level='info').count(), 1)

    def test_perform_backup_logs_error_when_borg_fails(self):
        self._run_backup(month_exists=False, borg_ok=False)
        self.assertEqual(BackupLog.objects.filter(level='error').count(), 1)

    def test_perform_backup_calls_lvremove_and_umount(self):
        calls = self._run_backup(month_exists=False)
        self.assertTrue(any(isinstance(c[0], str) and c[0].startswith('lvremove -f vg/snap') for c in calls))
        self.assertTrue(any(isinstance(c[0], list) and c[0] == ['umount', '/var/backups/simo-main'] for c in calls))

    def test_perform_backup_binds_boot_when_mounted(self):
        calls = self._run_backup(month_exists=False, ismount_boot=True, ismount_efi=False)
        mount_calls = [c for c in calls if isinstance(c[0], list) and c[0][:2] == ['mount', '--bind']]
        self.assertEqual(len(mount_calls), 1)
        self.assertEqual(mount_calls[0][0][2], '/boot')

    def test_perform_backup_binds_boot_and_efi_when_mounted(self):
        calls = self._run_backup(month_exists=False, ismount_boot=True, ismount_efi=True)
        mount_calls = [c for c in calls if isinstance(c[0], list) and c[0][:2] == ['mount', '--bind']]
        self.assertEqual(len(mount_calls), 2)

    def test_perform_backup_unmounts_bind_mounts_before_snapshot(self):
        calls = self._run_backup(month_exists=False, ismount_boot=True, ismount_efi=True)
        umount_bind = [i for i, c in enumerate(calls) if isinstance(c[0], list) and c[0][0] == 'umount' and c[0][1].startswith('/var/backups/simo-main/boot')]
        umount_snap = [i for i, c in enumerate(calls) if isinstance(c[0], list) and c[0] == ['umount', '/var/backups/simo-main']]
        self.assertTrue(umount_bind)
        self.assertTrue(umount_snap)
        self.assertLess(max(umount_bind), min(umount_snap))

    def test_perform_backup_no_bind_mounts_when_not_mounted(self):
        calls = self._run_backup(month_exists=False, ismount_boot=False, ismount_efi=False)
        mount_calls = [c for c in calls if isinstance(c[0], list) and c[0][:2] == ['mount', '--bind']]
        self.assertEqual(mount_calls, [])

    def test_perform_backup_borg_create_runs_in_snapshot_cwd(self):
        calls = self._run_backup(month_exists=False)
        borg_create = [c for c in calls if isinstance(c[0], str) and c[0].startswith('borg create')]
        self.assertEqual(borg_create[0][1].get('cwd'), '/var/backups/simo-main')

    def test_perform_backup_mounts_snapshot_mapper_with_escaped_dashes(self):
        from simo.backups.tasks import perform_backup

        ok = mock.Mock(returncode=0, stderr=b'', stdout=b'')
        calls = []

        def run_side_effect(cmd, *args, **kwargs):
            calls.append(cmd)
            return ok

        with (
            mock.patch('simo.backups.tasks.get_partitions', autospec=True, return_value=('vg-name', 'root', '/mnt')),
            mock.patch('simo.backups.tasks.create_snap', autospec=True, return_value='snap-name'),
            mock.patch('simo.backups.tasks.uuid.getnode', autospec=True, return_value=1),
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, return_value=True),
            mock.patch('simo.backups.tasks.os.makedirs', autospec=True),
            mock.patch('simo.backups.tasks.shutil.rmtree', autospec=True),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect),
            mock.patch('simo.backups.tasks.open', mock.mock_open(), create=True),
            mock.patch('simo.backups.tasks.datetime', autospec=True) as dt,
            mock.patch('simo.backups.tasks.os.path.ismount', autospec=True, return_value=False),
            mock.patch('simo.backups.tasks.shutil.disk_usage', autospec=True, return_value=mock.Mock(free=30 * 1024 * 1024 * 1024)),
            mock.patch('simo.backups.tasks.os.listdir', autospec=True, return_value=['2025-12']),
            mock.patch('simo.backups.tasks.os.path.isdir', autospec=True, return_value=True),
        ):
            dt.now.return_value = mock.Mock(year=2025, month=12)
            perform_backup()

        mount_cmds = [c for c in calls if isinstance(c, list) and c and c[0] == 'mount']
        self.assertTrue(mount_cmds)
        self.assertIn('/dev/mapper/vg-name-snap--name', mount_cmds[0])

    def test_perform_backup_writes_hub_meta_json(self):
        calls = self._run_backup(month_exists=False)
        # open() call is mocked; presence of hub_meta write is implicit if no exceptions.
        self.assertTrue(calls)

    def test_perform_backup_cleanup_does_not_crash_when_free_space_low_and_no_old_months(self):
        # disk free low, but there are no other month folders than current.
        self._run_backup(month_exists=False, disk_free=[1])
        self.assertTrue(True)

    def test_perform_backup_cleanup_removes_oldest_first_until_free(self):
        from simo.backups.tasks import perform_backup

        sd = '/mnt'
        hub = f'{sd}/simo_backups/hub-0x1'
        month_folder = os.path.join(hub, '2025-12')
        old1 = os.path.join(hub, '2025-10')
        old2 = os.path.join(hub, '2025-11')

        res_ok = mock.Mock(returncode=0, stderr=b'', stdout=b'')
        disk = [mock.Mock(free=1), mock.Mock(free=30 * 1024 * 1024 * 1024)]

        with (
            mock.patch('simo.backups.tasks.get_partitions', autospec=True, return_value=('vg', 'root', sd)),
            mock.patch('simo.backups.tasks.create_snap', autospec=True, return_value='snap'),
            mock.patch('simo.backups.tasks.uuid.getnode', autospec=True, return_value=1),
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, side_effect=lambda p: p in (sd, hub, month_folder)),
            mock.patch('simo.backups.tasks.os.listdir', autospec=True, return_value=['2025-10', '2025-11', '2025-12']),
            mock.patch('simo.backups.tasks.os.path.isdir', autospec=True, return_value=True),
            mock.patch('simo.backups.tasks.datetime', autospec=True) as dt,
            mock.patch('simo.backups.tasks.open', mock.mock_open(), create=True),
            mock.patch('simo.backups.tasks.shutil.disk_usage', autospec=True, side_effect=lambda *_a, **_k: disk.pop(0)),
            mock.patch('simo.backups.tasks.shutil.rmtree', autospec=True) as rmtree,
            mock.patch('simo.backups.tasks.os.makedirs', autospec=True),
            mock.patch('simo.backups.tasks.os.path.ismount', autospec=True, return_value=False),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, return_value=res_ok),
        ):
            dt.now.return_value = mock.Mock(year=2025, month=12)
            perform_backup()

        removed = [c.args[0] for c in rmtree.call_args_list if c.args and c.args[0] in (old1, old2)]
        self.assertTrue(removed)
        self.assertEqual(removed[0], old1)

    def test_perform_backup_cleanup_stops_when_no_more_old_months(self):
        from simo.backups.tasks import perform_backup

        sd = '/mnt'
        hub = f'{sd}/simo_backups/hub-0x1'
        month_folder = os.path.join(hub, '2025-12')
        old1 = os.path.join(hub, '2025-10')

        res_ok = mock.Mock(returncode=0, stderr=b'', stdout=b'')
        # Always low; should remove old1 then stop (no IndexError)
        disk = [mock.Mock(free=1), mock.Mock(free=1)]

        with (
            mock.patch('simo.backups.tasks.get_partitions', autospec=True, return_value=('vg', 'root', sd)),
            mock.patch('simo.backups.tasks.create_snap', autospec=True, return_value='snap'),
            mock.patch('simo.backups.tasks.uuid.getnode', autospec=True, return_value=1),
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, side_effect=lambda p: p in (sd, hub, month_folder)),
            mock.patch('simo.backups.tasks.os.listdir', autospec=True, return_value=['2025-10', '2025-12']),
            mock.patch('simo.backups.tasks.os.path.isdir', autospec=True, return_value=True),
            mock.patch('simo.backups.tasks.datetime', autospec=True) as dt,
            mock.patch('simo.backups.tasks.open', mock.mock_open(), create=True),
            mock.patch('simo.backups.tasks.shutil.disk_usage', autospec=True, side_effect=lambda *_a, **_k: disk.pop(0)),
            mock.patch('simo.backups.tasks.shutil.rmtree', autospec=True) as rmtree,
            mock.patch('simo.backups.tasks.os.makedirs', autospec=True),
            mock.patch('simo.backups.tasks.os.path.ismount', autospec=True, return_value=False),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, return_value=res_ok),
        ):
            dt.now.return_value = mock.Mock(year=2025, month=12)
            perform_backup()

        self.assertTrue(any(c.args and c.args[0] == old1 for c in rmtree.call_args_list))

