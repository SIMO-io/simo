from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase


class TestSaveConfig(SimpleTestCase):
    def test_save_config_writes_all_vpn_files_and_spawns_restart_thread(self):
        from simo.core.tasks import save_config

        data = {
            'vpn_ca': 'CA',
            'vpn_key': 'KEY',
            'vpn_crt': 'CRT',
            'vpn_ta': 'TA',
            'router_address': '1.2.3.4',
        }

        file_handles = {}

        def open_side_effect(path, mode='r', *args, **kwargs):
            handle = mock.MagicMock()
            handle.__enter__.return_value = handle
            file_handles[path] = handle
            return handle

        started = []

        def thread_ctor(*, target, **_kwargs):
            th = mock.Mock()
            th.start.side_effect = lambda: started.append(target)
            return th

        with (
            mock.patch('simo.core.tasks.open', side_effect=open_side_effect),
            mock.patch('simo.core.tasks.render_to_string', return_value='CONF'),
            mock.patch('simo.core.tasks.threading.Thread', side_effect=thread_ctor),
        ):
            save_config(data)

        self.assertIn('/etc/openvpn/client/simo_io.ca', file_handles)
        self.assertIn('/etc/openvpn/client/simo_io.key', file_handles)
        self.assertIn('/etc/openvpn/client/simo_io.crt', file_handles)
        self.assertIn('/etc/openvpn/client/simo_io.ta', file_handles)
        self.assertIn('/etc/openvpn/client/simo_io.conf', file_handles)

        file_handles['/etc/openvpn/client/simo_io.ca'].write.assert_called_once_with('CA')
        file_handles['/etc/openvpn/client/simo_io.key'].write.assert_called_once_with('KEY')
        file_handles['/etc/openvpn/client/simo_io.crt'].write.assert_called_once_with('CRT')
        file_handles['/etc/openvpn/client/simo_io.ta'].write.assert_called_once_with('TA')
        file_handles['/etc/openvpn/client/simo_io.conf'].write.assert_called_once_with('CONF')

        self.assertEqual(len(started), 1)
        self.assertTrue(callable(started[0]))

    def test_save_config_restart_thread_runs_expected_commands(self):
        from simo.core.tasks import save_config

        started = []

        def thread_ctor(*, target, **_kwargs):
            th = mock.Mock()
            th.start.side_effect = lambda: started.append(target)
            return th

        with (
            mock.patch('simo.core.tasks.open', mock.mock_open()),
            mock.patch('simo.core.tasks.render_to_string', return_value='CONF'),
            mock.patch('simo.core.tasks.threading.Thread', side_effect=thread_ctor),
        ):
            save_config({'router_address': '1.2.3.4'})

        self.assertEqual(len(started), 1)
        restart_fn = started[0]

        with (
            mock.patch('simo.core.tasks.time.sleep', autospec=True),
            mock.patch('simo.core.tasks.subprocess.run', autospec=True) as run,
            mock.patch('builtins.print'),
        ):
            restart_fn()

        expected = [
            ['/usr/bin/systemctl', 'enable', 'openvpn-client@simo_io.service'],
            ['/usr/bin/systemctl', 'restart', 'openvpn-client@simo_io.service'],
            ['service', 'openvpn', 'reload'],
        ]
        self.assertEqual([c.args[0] for c in run.call_args_list], expected)

    def test_save_config_does_not_spawn_thread_without_vpn_keys(self):
        from simo.core.tasks import save_config

        with mock.patch('simo.core.tasks.threading.Thread', autospec=True) as thread:
            save_config({})

        thread.assert_not_called()

    def test_save_config_swallow_write_errors_but_still_spawns_thread(self):
        from simo.core.tasks import save_config

        started = []

        def thread_ctor(*, target, **_kwargs):
            th = mock.Mock()
            th.start.side_effect = lambda: started.append(target)
            return th

        def open_side_effect(*_args, **_kwargs):
            raise OSError('nope')

        with (
            mock.patch('simo.core.tasks.open', side_effect=open_side_effect),
            mock.patch('simo.core.tasks.threading.Thread', side_effect=thread_ctor),
            mock.patch('builtins.print') as printer,
        ):
            save_config({'vpn_ca': 'CA'})

        printer.assert_called()
        self.assertEqual(len(started), 1)
