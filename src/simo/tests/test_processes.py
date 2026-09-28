from unittest import mock

from .base import BaseSimoTestCase


class ParentDeathSignalTests(BaseSimoTestCase):
    def test_installs_linux_parent_death_signal(self):
        from simo.core.utils import processes

        libc = mock.Mock()
        libc.prctl.return_value = 0
        with (
            mock.patch.object(processes.sys, 'platform', 'linux'),
            mock.patch.object(processes.os, 'getppid', side_effect=[101, 101]),
            mock.patch.object(processes.ctypes, 'CDLL', return_value=libc),
        ):
            processes.install_parent_death_signal()

        libc.prctl.assert_called_once_with(
            processes._PR_SET_PDEATHSIG, processes.signal.SIGTERM
        )

    def test_exits_when_parent_dies_during_signal_setup(self):
        from simo.core.utils import processes

        libc = mock.Mock()
        libc.prctl.return_value = 0
        with (
            mock.patch.object(processes.sys, 'platform', 'linux'),
            mock.patch.object(processes.os, 'getppid', side_effect=[101, 1]),
            mock.patch.object(processes.ctypes, 'CDLL', return_value=libc),
            mock.patch.object(processes.os, '_exit') as exit_process,
        ):
            processes.install_parent_death_signal()

        exit_process.assert_called_once_with(1)
