import json
import os
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from .base import BaseSimoTestCase


class CreateSnapTests(BaseSimoTestCase):
    def test_create_snap_generates_name_when_missing(self):
        from simo.backups.tasks import create_snap

        def run_side_effect(cmd, shell=True, stdout=None, stderr=None):
            if cmd == 'vgs --report-format json':
                return mock.Mock(stdout=json.dumps({'report': [{'vg': [{'vg_free': '10g'}]}]}).encode(), returncode=0)
            if cmd.startswith('lvs --report-format json'):
                return mock.Mock(stdout=json.dumps({'report': [{'lv': []}]}).encode(), returncode=0)
            if cmd.startswith('lvcreate -s'):
                return mock.Mock(returncode=0, stderr=b'')
            raise AssertionError(cmd)

        with (
            mock.patch('simo.backups.tasks.get_random_string', autospec=True, return_value='abcde'),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect) as run,
        ):
            snap = create_snap('vg', 'root')

        self.assertEqual(snap, 'root-bk-abcde')
        self.assertTrue(any('lvcreate -s -n root-bk-abcde' in c.args[0] for c in run.call_args_list))

    def test_create_snap_uses_full_free_space_when_size_missing(self):
        from simo.backups.tasks import create_snap

        def run_side_effect(cmd, shell=True, stdout=None, stderr=None):
            if cmd == 'vgs --report-format json':
                return mock.Mock(stdout=json.dumps({'report': [{'vg': [{'vg_free': '7g'}]}]}).encode(), returncode=0)
            if cmd.startswith('lvs --report-format json'):
                return mock.Mock(stdout=json.dumps({'report': [{'lv': []}]}).encode(), returncode=0)
            if cmd.startswith('lvcreate -s'):
                return mock.Mock(returncode=0, stderr=b'')
            raise AssertionError(cmd)

        with (
            mock.patch('simo.backups.tasks.get_random_string', autospec=True, return_value='x'),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect) as run,
        ):
            create_snap('vg', 'root')

        lvcreate_cmds = [c.args[0] for c in run.call_args_list if isinstance(c.args[0], str) and c.args[0].startswith('lvcreate')]
        self.assertEqual(len(lvcreate_cmds), 1)
        self.assertIn('-L 7G', lvcreate_cmds[0])

    def test_create_snap_raises_if_lvcreate_fails(self):
        from simo.backups.tasks import create_snap

        def run_side_effect(cmd, shell=True, stdout=None, stderr=None):
            if cmd == 'vgs --report-format json':
                return mock.Mock(stdout=json.dumps({'report': [{'vg': [{'vg_free': '7g'}]}]}).encode(), returncode=0)
            if cmd.startswith('lvs --report-format json'):
                return mock.Mock(stdout=json.dumps({'report': [{'lv': []}]}).encode(), returncode=0)
            if cmd.startswith('lvcreate -s'):
                return mock.Mock(returncode=1, stderr=b'bad')
            raise AssertionError(cmd)

        with (
            mock.patch('simo.backups.tasks.get_random_string', autospec=True, return_value='x'),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect),
        ):
            with self.assertRaises(Exception):
                create_snap('vg', 'root')

    def test_create_snap_retries_when_vgs_json_invalid(self):
        from simo.backups.tasks import create_snap

        calls = {'n': 0}

        def run_side_effect(cmd, shell=True, stdout=None, stderr=None):
            if cmd.startswith('lvs --report-format json'):
                return mock.Mock(stdout=json.dumps({'report': [{'lv': []}]}).encode(), returncode=0)
            if cmd == 'vgs --report-format json':
                calls['n'] += 1
                if calls['n'] < 2:
                    return mock.Mock(stdout=b'not-json', returncode=0)
                return mock.Mock(stdout=json.dumps({'report': [{'vg': [{'vg_free': '7g'}]}]}).encode(), returncode=0)
            if cmd.startswith('lvcreate -s'):
                return mock.Mock(returncode=0, stderr=b'')
            raise AssertionError(cmd)

        with (
            mock.patch('simo.backups.tasks.get_random_string', autospec=True, return_value='x'),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect),
        ):
            create_snap('vg', 'root')

        self.assertEqual(calls['n'], 2)

    def test_create_snap_raises_when_free_space_format_unexpected(self):
        from simo.backups.tasks import create_snap

        def run_side_effect(cmd, shell=True, stdout=None, stderr=None):
            if cmd.startswith('lvs --report-format json'):
                return mock.Mock(stdout=json.dumps({'report': [{'lv': []}]}).encode(), returncode=0)
            if cmd == 'vgs --report-format json':
                return mock.Mock(stdout=json.dumps({'report': [{'vg': [{'vg_free': '100m'}]}]}).encode(), returncode=0)
            raise AssertionError(cmd)

        with (
            mock.patch('simo.backups.tasks.get_random_string', autospec=True, return_value='x'),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect),
        ):
            with self.assertRaises(Exception):
                create_snap('vg', 'root')

    def test_create_snap_raises_when_requested_size_exceeds_free(self):
        from simo.backups.tasks import create_snap

        def run_side_effect(cmd, shell=True, stdout=None, stderr=None):
            if cmd.startswith('lvs --report-format json'):
                return mock.Mock(stdout=json.dumps({'report': [{'lv': []}]}).encode(), returncode=0)
            if cmd == 'vgs --report-format json':
                return mock.Mock(stdout=json.dumps({'report': [{'vg': [{'vg_free': '7g'}]}]}).encode(), returncode=0)
            raise AssertionError(cmd)

        with (
            mock.patch('simo.backups.tasks.get_random_string', autospec=True, return_value='x'),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect),
        ):
            with self.assertRaises(Exception):
                create_snap('vg', 'root', size=99)


class CleanBackupSnapsTests(BaseSimoTestCase):
    def test_clean_backup_snaps_removes_matching_snapshots(self):
        from simo.backups.tasks import clean_backup_snaps

        lvs_json = {
            'report': [
                {
                    'lv': [
                        {'vg_name': 'vg', 'origin': 'root', 'lv_name': 'root-bk-aaa'},
                        {'vg_name': 'vg', 'origin': 'root', 'lv_name': 'root-bk-bbb'},
                        {'vg_name': 'vg', 'origin': 'other', 'lv_name': 'root-bk-ccc'},
                        {'vg_name': 'x', 'origin': 'root', 'lv_name': 'root-bk-ddd'},
                        {'vg_name': 'vg', 'origin': 'root', 'lv_name': 'root-snap'},
                    ]
                }
            ]
        }

        calls = []

        def run_side_effect(cmd, shell=True, stdout=None, stderr=None):
            calls.append(cmd)
            if cmd == 'lvs --report-format json':
                return mock.Mock(stdout=json.dumps(lvs_json).encode(), returncode=0)
            return mock.Mock(returncode=0)

        with mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect):
            clean_backup_snaps('vg', 'root')

        rm_calls = [c for c in calls if isinstance(c, str) and c.startswith('lvremove')]
        self.assertEqual(rm_calls, ['lvremove -f vg/root-bk-aaa', 'lvremove -f vg/root-bk-bbb'])

    def test_clean_backup_snaps_noop_when_no_matches(self):
        from simo.backups.tasks import clean_backup_snaps

        lvs_json = {'report': [{'lv': [{'vg_name': 'vg', 'origin': 'x', 'lv_name': 'root-bk-aaa'}]}]}

        def run_side_effect(cmd, shell=True, stdout=None, stderr=None):
            if cmd == 'lvs --report-format json':
                return mock.Mock(stdout=json.dumps(lvs_json).encode(), returncode=0)
            raise AssertionError('unexpected lvremove')

        with mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect):
            clean_backup_snaps('vg', 'root')


class GetPartitionsTests(BaseSimoTestCase):
    def test_get_partitions_logs_when_no_lvm(self):
        from simo.backups.models import BackupLog
        from simo.backups.tasks import get_partitions

        BackupLog.objects.all().delete()

        with mock.patch(
            'simo.backups.tasks.subprocess.check_output',
            autospec=True,
            return_value=json.dumps({'blockdevices': []}).encode(),
        ):
            res = get_partitions()

        self.assertIsNone(res)
        self.assertEqual(BackupLog.objects.count(), 1)

    def test_get_partitions_logs_when_lvm_name_unexpected(self):
        from simo.backups.models import BackupLog
        from simo.backups.tasks import get_partitions

        BackupLog.objects.all().delete()
        lsblk = {
            'blockdevices': [
                {'type': 'lvm', 'mountpoint': '/', 'name': 'rootlv', 'children': []},
            ]
        }

        with mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=json.dumps(lsblk).encode()):
            res = get_partitions()

        self.assertIsNone(res)
        self.assertEqual(BackupLog.objects.count(), 1)

    def test_get_partitions_mounts_backup_device_to_expected_mountpoint(self):
        from simo.backups.tasks import get_partitions

        lsblk = {
            'blockdevices': [
                {'type': 'lvm', 'mountpoint': '/', 'name': 'vg-root', 'children': []},
                {'name': 'sda', 'hotplug': True, 'children': [{'name': 'sda3', 'label': 'BACKUP', 'mountpoint': '/old'}]},
            ]
        }

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=json.dumps(lsblk).encode()),
            mock.patch('simo.backups.tasks.get_backup_device', autospec=True, return_value={'name': 'sda3', 'label': 'BACKUP', 'mountpoint': '/old'}),
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, return_value=True),
            mock.patch('simo.backups.tasks.subprocess.call', autospec=True) as call,
        ):
            res = get_partitions()

        self.assertEqual(res, ('vg', 'root', '/media/BACKUP'))
        # Should unmount old mountpoint and mount to /media/BACKUP.
        self.assertTrue(any('umount /old' in str(c.args[0]) for c in call.call_args_list))
        self.assertTrue(any('mount /dev/sda3 /media/BACKUP' in str(c.args[0]) for c in call.call_args_list))

    def test_get_partitions_mountpoint_prefers_partlabel_over_label(self):
        from simo.backups.tasks import get_partitions

        lsblk = {
            'blockdevices': [
                {'type': 'lvm', 'mountpoint': '/', 'name': 'vg-root', 'children': []},
                {'name': 'sda', 'hotplug': True, 'children': [{'name': 'sda3', 'label': 'LBL', 'partlabel': 'PL', 'mountpoint': None}]},
            ]
        }

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=json.dumps(lsblk).encode()),
            mock.patch('simo.backups.tasks.get_backup_device', autospec=True, return_value={'name': 'sda3', 'label': 'LBL', 'partlabel': 'PL', 'mountpoint': None}),
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, return_value=True),
            mock.patch('simo.backups.tasks.subprocess.call', autospec=True),
        ):
            res = get_partitions()

        self.assertEqual(res, ('vg', 'root', '/media/PL'))

    def test_get_partitions_mountpoint_uses_name_when_no_labels(self):
        from simo.backups.tasks import get_partitions

        lsblk = {
            'blockdevices': [
                {'type': 'lvm', 'mountpoint': '/', 'name': 'vg-root', 'children': []},
                {'name': 'sda', 'hotplug': True, 'children': [{'name': 'sda3', 'mountpoint': None}]},
            ]
        }

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=json.dumps(lsblk).encode()),
            mock.patch('simo.backups.tasks.get_backup_device', autospec=True, return_value={'name': 'sda3', 'mountpoint': None}),
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, return_value=True),
            mock.patch('simo.backups.tasks.subprocess.call', autospec=True),
        ):
            res = get_partitions()

        self.assertEqual(res, ('vg', 'root', '/media/sda3'))

    def test_get_partitions_auto_prepares_blank_device(self):
        from simo.backups.tasks import get_partitions

        lsblk1 = {'blockdevices': [{'type': 'lvm', 'mountpoint': '/', 'name': 'vg-root', 'children': []}]}
        lsblk2 = {
            'blockdevices': [
                {'type': 'lvm', 'mountpoint': '/', 'name': 'vg-root', 'children': []},
                {'name': 'sda', 'hotplug': True, 'children': [{'name': 'sda3', 'label': 'BACKUP', 'mountpoint': None}]},
            ]
        }

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, side_effect=[json.dumps(lsblk1).encode(), json.dumps(lsblk2).encode()]),
            mock.patch('simo.backups.tasks.get_backup_device', autospec=True, side_effect=[None, {'name': 'sda3', 'label': 'BACKUP', 'mountpoint': None}]),
            mock.patch('simo.backups.tasks._find_blank_removable_device', autospec=True, return_value={'name': 'sda'}),
            mock.patch('simo.backups.tasks._ensure_rescue_image_written', autospec=True),
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, return_value=True),
            mock.patch('simo.backups.tasks.subprocess.call', autospec=True),
        ):
            res = get_partitions()

        self.assertEqual(res, ('vg', 'root', '/media/BACKUP'))

    def test_get_partitions_logs_error_when_auto_prepare_fails(self):
        from simo.backups.models import BackupLog
        from simo.backups.tasks import get_partitions

        BackupLog.objects.all().delete()
        lsblk = {'blockdevices': [{'type': 'lvm', 'mountpoint': '/', 'name': 'vg-root', 'children': []}]}

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=json.dumps(lsblk).encode()),
            mock.patch('simo.backups.tasks.get_backup_device', autospec=True, return_value=None),
            mock.patch('simo.backups.tasks._find_blank_removable_device', autospec=True, return_value={'name': 'sda'}),
            mock.patch('simo.backups.tasks._ensure_rescue_image_written', autospec=True, side_effect=RuntimeError('boom')),
        ):
            res = get_partitions()

        self.assertIsNone(res)
        self.assertEqual(BackupLog.objects.filter(level='error').count(), 1)


class BackupTasksRestoreAndCleanupTests(BaseSimoTestCase):
    def test_restore_backup_logs_error_when_no_partitions(self):
        from simo.backups.models import Backup, BackupLog
        from simo.backups.tasks import restore_backup

        BackupLog.objects.all().delete()
        backup = Backup.objects.create(datetime=timezone.now(), mac='m', filepath='x::y')

        with mock.patch('simo.backups.tasks.get_partitions', autospec=True, side_effect=RuntimeError('no lvm')):
            restore_backup(backup.id)

        self.assertEqual(BackupLog.objects.filter(level='error').count(), 1)

    def test_restore_backup_logs_error_when_create_snap_fails(self):
        from simo.backups.models import Backup, BackupLog
        from simo.backups.tasks import restore_backup

        BackupLog.objects.all().delete()
        backup = Backup.objects.create(datetime=timezone.now(), mac='m', filepath='x::y')

        with (
            mock.patch('simo.backups.tasks.get_partitions', autospec=True, return_value=('vg', 'root', '/mnt')),
            mock.patch('simo.backups.tasks.create_snap', autospec=True, side_effect=RuntimeError('boom')),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True),
        ):
            restore_backup(backup.id)

        self.assertEqual(BackupLog.objects.filter(level='error').count(), 1)

    def test_restore_backup_success_merges_snapshot_and_reboots_without_lvremove(self):
        from simo.backups.models import Backup
        from simo.backups.tasks import restore_backup

        backup = Backup.objects.create(datetime=timezone.now(), mac='m', filepath='x::y')

        res = mock.Mock(returncode=0, stderr=b'')
        with (
            mock.patch('simo.backups.tasks.get_partitions', autospec=True, return_value=('vg', 'root', '/mnt')),
            mock.patch('simo.backups.tasks.create_snap', autospec=True, return_value='snap'),
            mock.patch('simo.backups.tasks.os.listdir', autospec=True, return_value=['a']),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, return_value=res) as run,
            mock.patch('simo.backups.tasks.subprocess.call', autospec=True) as call,
            mock.patch('simo.backups.tasks.os.makedirs', autospec=True),
            mock.patch('simo.backups.tasks.shutil.rmtree', autospec=True),
        ):
            restore_backup(backup.id)

        self.assertTrue(any('lvconvert --mergesnapshot vg/snap' in str(c.args[0]) for c in call.call_args_list))
        # With success, we should not run lvremove - snapshot must exist for merge.
        self.assertFalse(any(isinstance(c.args[0], str) and 'lvremove -f vg/snap' in c.args[0] for c in run.call_args_list))
        self.assertTrue(any(isinstance(c.args[0], str) and c.args[0] == 'reboot' for c in run.call_args_list))

    def test_restore_backup_error_lvremoves_snapshot(self):
        from simo.backups.models import Backup, BackupLog
        from simo.backups.tasks import restore_backup

        BackupLog.objects.all().delete()
        backup = Backup.objects.create(datetime=timezone.now(), mac='m', filepath='x::y')

        def run_side_effect(cmd, *args, **kwargs):
            if isinstance(cmd, str) and cmd.startswith('borg extract'):
                return mock.Mock(returncode=1, stderr=b'fail')
            return mock.Mock(returncode=0, stderr=b'')

        with (
            mock.patch('simo.backups.tasks.get_partitions', autospec=True, return_value=('vg', 'root', '/mnt')),
            mock.patch('simo.backups.tasks.create_snap', autospec=True, return_value='snap'),
            mock.patch('simo.backups.tasks.os.listdir', autospec=True, return_value=[]),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect) as run,
            mock.patch('simo.backups.tasks.os.makedirs', autospec=True),
            mock.patch('simo.backups.tasks.shutil.rmtree', autospec=True),
        ):
            restore_backup(backup.id)

        self.assertTrue(any(isinstance(c.args[0], str) and 'lvremove -f vg/snap' in c.args[0] for c in run.call_args_list))
        self.assertEqual(BackupLog.objects.filter(level='error').count(), 1)

    def test_restore_backup_error_does_not_reboot(self):
        from simo.backups.models import Backup
        from simo.backups.tasks import restore_backup

        backup = Backup.objects.create(datetime=timezone.now(), mac='m', filepath='x::y')

        def run_side_effect(cmd, *args, **kwargs):
            if isinstance(cmd, str) and cmd.startswith('borg extract'):
                return mock.Mock(returncode=1, stderr=b'fail')
            return mock.Mock(returncode=0, stderr=b'')

        with (
            mock.patch('simo.backups.tasks.get_partitions', autospec=True, return_value=('vg', 'root', '/mnt')),
            mock.patch('simo.backups.tasks.create_snap', autospec=True, return_value='snap'),
            mock.patch('simo.backups.tasks.os.listdir', autospec=True, return_value=[]),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect) as run,
            mock.patch('simo.backups.tasks.os.makedirs', autospec=True),
            mock.patch('simo.backups.tasks.shutil.rmtree', autospec=True),
        ):
            restore_backup(backup.id)

        self.assertFalse(any(isinstance(c.args[0], str) and c.args[0] == 'reboot' for c in run.call_args_list))


class BackupDriveProvisioningTests(BaseSimoTestCase):
    def test_ensure_rescue_image_written_invokes_dd_and_expand(self):
        from simo.backups.tasks import _ensure_rescue_image_written

        ok = mock.Mock(returncode=0, stderr=b'')
        with (
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, return_value=ok) as run,
            mock.patch('time.sleep', autospec=True),
            mock.patch('simo.backups.tasks._expand_backup_partition', autospec=True) as expand,
        ):
            _ensure_rescue_image_written('sda')

        self.assertTrue(any(isinstance(c.args[0], str) and 'dd of=/dev/sda' in c.args[0] for c in run.call_args_list))
        self.assertTrue(any(isinstance(c.args[0], str) and c.args[0] == 'partprobe /dev/sda' for c in run.call_args_list))
        expand.assert_called_once_with('sda')

    def test_ensure_rescue_image_written_raises_on_dd_failure(self):
        from simo.backups.tasks import _ensure_rescue_image_written

        fail = mock.Mock(returncode=1, stderr=b'bad')
        with mock.patch('simo.backups.tasks.subprocess.run', autospec=True, return_value=fail):
            with self.assertRaises(RuntimeError):
                _ensure_rescue_image_written('sda')

    def test_expand_backup_partition_uses_p3_path_when_direct_missing(self):
        from simo.backups.tasks import _expand_backup_partition

        ok = mock.Mock(returncode=0, stderr=b'')

        def exists(path):
            # direct /dev/sda3 missing, /dev/sdap3 exists
            return path == '/dev/sdap3'

        def run_side_effect(cmd, *args, **kwargs):
            if isinstance(cmd, str) and cmd.startswith('mkfs.ext4'):
                return ok
            if isinstance(cmd, str) and cmd.startswith('sgdisk -n'):
                return ok
            return ok

        with (
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, side_effect=exists),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect) as run,
            mock.patch('time.sleep', autospec=True),
        ):
            _expand_backup_partition('sda')

        mkfs_calls = [c.args[0] for c in run.call_args_list if isinstance(c.args[0], str) and c.args[0].startswith('mkfs.ext4')]
        self.assertEqual(mkfs_calls, ['mkfs.ext4 -F -L BACKUP /dev/sdap3'])

    def test_expand_backup_partition_raises_on_sgdisk_failure(self):
        from simo.backups.tasks import _expand_backup_partition

        ok = mock.Mock(returncode=0, stderr=b'')
        bad = mock.Mock(returncode=1, stderr=b'nope')

        def run_side_effect(cmd, *args, **kwargs):
            if isinstance(cmd, str) and cmd.startswith('sgdisk -n'):
                return bad
            return ok

        with (
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, return_value=True),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect),
        ):
            with self.assertRaises(RuntimeError):
                _expand_backup_partition('sda')

    def test_expand_backup_partition_raises_when_dev_node_never_appears(self):
        from simo.backups.tasks import _expand_backup_partition

        ok = mock.Mock(returncode=0, stderr=b'')

        with (
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, return_value=False),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, return_value=ok),
            mock.patch('time.sleep', autospec=True),
        ):
            with self.assertRaises(RuntimeError):
                _expand_backup_partition('sda')

    def test_expand_backup_partition_raises_on_mkfs_failure(self):
        from simo.backups.tasks import _expand_backup_partition

        ok = mock.Mock(returncode=0, stderr=b'')
        bad = mock.Mock(returncode=1, stderr=b'bad')

        def run_side_effect(cmd, *args, **kwargs):
            if isinstance(cmd, str) and cmd.startswith('mkfs.ext4'):
                return bad
            if isinstance(cmd, str) and cmd.startswith('sgdisk -n'):
                return ok
            return ok

        with (
            mock.patch('simo.backups.tasks.os.path.exists', autospec=True, return_value=True),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, side_effect=run_side_effect),
        ):
            with self.assertRaises(RuntimeError):
                _expand_backup_partition('sda')

    def test_clean_old_logs_deletes_rows(self):
        from simo.backups.models import BackupLog
        from simo.backups.tasks import clean_old_logs

        old = timezone.now() - timedelta(days=120)
        old_obj = BackupLog.objects.create(level='info', msg='x')
        BackupLog.objects.filter(pk=old_obj.pk).update(datetime=old)
        BackupLog.objects.create(level='info', msg='y')

        clean_old_logs()

        self.assertEqual(BackupLog.objects.count(), 1)

    def test_perform_backup_deletes_oldest_month_folder_first(self):
        from simo.backups.tasks import perform_backup

        res_ok = mock.Mock(returncode=0, stderr=b'', stdout=b'')
        sd = '/mnt'
        hub = f'{sd}/simo_backups/hub-0x1'
        month_folder = os.path.join(hub, '2025-12')
        old1 = os.path.join(hub, '2025-10')
        old2 = os.path.join(hub, '2025-11')

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
        # Oldest (2025-10) removed first.
        self.assertEqual(removed[0], old1)
