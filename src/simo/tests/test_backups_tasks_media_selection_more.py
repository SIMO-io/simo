import contextlib
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase


@contextlib.contextmanager
def _scandir(names):
    yield [SimpleNamespace(name=n) for n in names]


class BackupsMediaSelectionMoreTests(SimpleTestCase):
    def test_find_blank_removable_device_returns_whole_disk_when_only_lost_found(self):
        from simo.backups.tasks import _find_blank_removable_device

        lsblk = [
            {
                'name': 'sda',
                'hotplug': True,
                'children': [],
                'fstype': 'ext4',
                'mountpoint': '/mnt',
            }
        ]

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b'34359738368'),
            mock.patch('simo.backups.tasks.os.scandir', autospec=True, side_effect=lambda *_a, **_k: _scandir(['lost+found'])),
        ):
            dev = _find_blank_removable_device(lsblk)

        self.assertEqual(dev['name'], 'sda')

    def test_find_blank_removable_device_returns_none_when_files_present(self):
        from simo.backups.tasks import _find_blank_removable_device

        lsblk = [
            {
                'name': 'sda',
                'hotplug': True,
                'children': [],
                'fstype': 'ext4',
                'mountpoint': '/mnt',
            }
        ]

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b'34359738368'),
            mock.patch('simo.backups.tasks.os.scandir', autospec=True, side_effect=lambda *_a, **_k: _scandir(['lost+found', 'file.txt'])),
        ):
            dev = _find_blank_removable_device(lsblk)

        self.assertIsNone(dev)

    def test_find_blank_removable_device_returns_device_when_single_partition_empty(self):
        from simo.backups.tasks import _find_blank_removable_device

        lsblk = [
            {
                'name': 'sda',
                'hotplug': True,
                'children': [{'name': 'sda1', 'fstype': 'ext4', 'mountpoint': '/mnt'}],
            }
        ]

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b'34359738368'),
            mock.patch('simo.backups.tasks.os.scandir', autospec=True, side_effect=lambda *_a, **_k: _scandir(['lost+found'])),
        ):
            dev = _find_blank_removable_device(lsblk)

        self.assertEqual(dev['name'], 'sda')

    def test_find_blank_removable_device_skips_devices_with_multiple_partitions(self):
        from simo.backups.tasks import _find_blank_removable_device

        lsblk = [
            {
                'name': 'sda',
                'hotplug': True,
                'children': [
                    {'name': 'sda1', 'fstype': 'ext4', 'mountpoint': '/mnt1'},
                    {'name': 'sda2', 'fstype': 'ext4', 'mountpoint': '/mnt2'},
                ],
            }
        ]

        with mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b'34359738368'):
            dev = _find_blank_removable_device(lsblk)
        self.assertIsNone(dev)

    def test_find_blank_removable_device_mount_failure_returns_none(self):
        from simo.backups.tasks import _find_blank_removable_device

        lsblk = [{'name': 'sda', 'hotplug': True, 'children': [], 'fstype': 'ext4', 'mountpoint': None}]

        mount_res = mock.Mock(returncode=1, stderr=b'nope')

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b'34359738368'),
            mock.patch('simo.backups.tasks.subprocess.run', autospec=True, return_value=mount_res),
        ):
            dev = _find_blank_removable_device(lsblk)
        self.assertIsNone(dev)

    def test_find_blank_removable_device_scandir_error_returns_none(self):
        from simo.backups.tasks import _find_blank_removable_device

        lsblk = [{'name': 'sda', 'hotplug': True, 'children': [], 'fstype': 'ext4', 'mountpoint': '/mnt'}]

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b'34359738368'),
            mock.patch('simo.backups.tasks.os.scandir', autospec=True, side_effect=OSError('boom')),
        ):
            dev = _find_blank_removable_device(lsblk)
        self.assertIsNone(dev)

    def test_get_backup_device_legacy_prefers_existing_simo_backups(self):
        from simo.backups.tasks import get_backup_device

        lsblk = [
            {
                'name': 'sda',
                'hotplug': True,
                'children': [],
                'fstype': 'ext4',
                'mountpoint': '/mnt',
            }
        ]

        def _isdir(path):
            return path.endswith('/simo_backups')

        with (
            mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b'34359738368'),
            mock.patch('simo.backups.tasks._find_blank_removable_device', autospec=True, return_value=None),
            mock.patch('simo.backups.tasks.os.path.isdir', autospec=True, side_effect=_isdir),
        ):
            dev = get_backup_device(lsblk)

        self.assertEqual(dev['name'], 'sda')

