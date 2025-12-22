from unittest import mock

from django.test import SimpleTestCase


class BackupsHelpersTests(SimpleTestCase):
    def test_get_lvm_partition_finds_nested_root(self):
        from simo.backups.tasks import get_lvm_partition

        lsblk = [
            {
                'name': 'sda',
                'children': [
                    {'name': 'sda1', 'type': 'part', 'mountpoint': '/boot'},
                ],
            },
            {
                'name': 'sdb',
                'children': [
                    {
                        'name': 'vg0-root',
                        'type': 'lvm',
                        'mountpoint': '/',
                    }
                ],
            },
        ]
        entry = get_lvm_partition(lsblk)
        self.assertIsNotNone(entry)
        self.assertEqual(entry['name'], 'vg0-root')

    def test_has_backup_label_accepts_label_or_partlabel(self):
        from simo.backups.tasks import _has_backup_label

        self.assertTrue(_has_backup_label({'label': 'BACKUP'}))
        self.assertTrue(_has_backup_label({'partlabel': 'backup'}))
        self.assertFalse(_has_backup_label({'label': 'DATA'}))

    def test_find_blank_removable_device_returns_whole_disk(self):
        from simo.backups import tasks

        lsblk = [
            {'name': 'sda', 'hotplug': 1, 'fstype': None, 'mountpoint': None},
        ]
        with mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b"40000000000"):
            dev = tasks._find_blank_removable_device(lsblk)
        self.assertIsNotNone(dev)
        self.assertEqual(dev['name'], 'sda')

    def test_get_backup_device_prefers_backup_label(self):
        from simo.backups.tasks import get_backup_device

        lsblk = [
            {
                'name': 'sda',
                'hotplug': 1,
                'children': [
                    {'name': 'sda3', 'label': 'BACKUP', 'fstype': 'ext4'},
                ],
            }
        ]
        with mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b"40000000000"):
            dev = get_backup_device(lsblk)
        self.assertIsNotNone(dev)
        self.assertEqual(dev['name'], 'sda3')

    def test_get_backup_device_returns_none_when_blank_is_available(self):
        from simo.backups import tasks

        lsblk = [
            {'name': 'sda', 'hotplug': 1, 'children': []},
        ]
        with mock.patch('simo.backups.tasks._find_blank_removable_device', autospec=True, return_value={'name': 'sda'}), \
                mock.patch('simo.backups.tasks.subprocess.check_output', autospec=True, return_value=b"40000000000"):
            dev = tasks.get_backup_device(lsblk)
        self.assertIsNone(dev)

