from unittest import mock

from django.test import SimpleTestCase


class BackupsTasksHelpersTests(SimpleTestCase):
    def test_get_lvm_partition_finds_root_at_top_level(self):
        from simo.backups.tasks import get_lvm_partition

        data = [
            {'type': 'lvm', 'mountpoint': '/', 'name': 'root'},
            {'type': 'part', 'mountpoint': None, 'name': 'x'},
        ]
        self.assertEqual(get_lvm_partition(data)['name'], 'root')

    def test_get_lvm_partition_finds_root_nested(self):
        from simo.backups.tasks import get_lvm_partition

        data = [
            {
                'type': 'disk',
                'name': 'sda',
                'children': [
                    {'type': 'part', 'name': 'sda1', 'children': []},
                ],
            },
            {
                'type': 'disk',
                'name': 'sdb',
                'children': [
                    {
                        'type': 'part',
                        'name': 'sdb1',
                        'children': [{'type': 'lvm', 'mountpoint': '/', 'name': 'vg-root'}],
                    }
                ],
            },
        ]
        self.assertEqual(get_lvm_partition(data)['name'], 'vg-root')

    def test_get_lvm_partition_returns_none_when_missing(self):
        from simo.backups.tasks import get_lvm_partition

        data = [{'type': 'disk', 'name': 'sda', 'children': []}]
        self.assertIsNone(get_lvm_partition(data))

    def test_has_backup_label_reads_label_and_partlabel(self):
        from simo.backups.tasks import _has_backup_label

        self.assertTrue(_has_backup_label({'label': 'BACKUP'}))
        self.assertTrue(_has_backup_label({'label': 'backup'}))
        self.assertTrue(_has_backup_label({'partlabel': 'BACKUP'}))
        self.assertFalse(_has_backup_label({'label': 'DATA'}))

    def test_get_backup_device_prefers_backup_partition_with_capacity(self):
        from simo.backups.tasks import get_backup_device

        lsblk = [
            {
                'name': 'sda',
                'hotplug': True,
                'children': [{'name': 'sda3', 'label': 'BACKUP'}],
            }
        ]

        with mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b'34359738368'):
            dev = get_backup_device(lsblk)
        self.assertEqual(dev['name'], 'sda3')

    def test_get_backup_device_skips_small_devices(self):
        from simo.backups.tasks import get_backup_device

        lsblk = [
            {
                'name': 'sda',
                'hotplug': True,
                'children': [{'name': 'sda3', 'label': 'BACKUP'}],
            }
        ]

        with mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b'1024'):
            self.assertIsNone(get_backup_device(lsblk))

    def test_get_backup_device_returns_none_when_blank_device_available(self):
        from simo.backups.tasks import get_backup_device

        lsblk = [{'name': 'sda', 'hotplug': True, 'children': []}]

        with mock.patch('simo.backups.tasks._find_blank_removable_device', autospec=True, return_value={'name': 'sda'}):
            self.assertIsNone(get_backup_device(lsblk))

    def test_find_blank_removable_device_returns_whole_disk_unformatted(self):
        from simo.backups.tasks import _find_blank_removable_device

        lsblk = [{'name': 'sda', 'hotplug': True, 'children': [], 'fstype': None}]

        with mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b'34359738368'):
            dev = _find_blank_removable_device(lsblk)
        self.assertEqual(dev['name'], 'sda')

