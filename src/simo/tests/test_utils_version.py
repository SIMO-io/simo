from __future__ import annotations

from unittest import mock
from unittest import TestCase


class TestVersionHelpers(TestCase):
    def test_get_package_version_returns_metadata_version(self):
        from simo.core.utils import version

        with mock.patch.object(version.metadata, 'version', return_value='1.2.3'):
            self.assertEqual(version.get_package_version('simo'), '1.2.3')

    def test_get_package_version_falls_back_on_missing_package(self):
        from simo.core.utils import version

        with mock.patch.object(
            version.metadata,
            'version',
            side_effect=version.metadata.PackageNotFoundError('simo'),
        ):
            self.assertEqual(version.get_package_version('simo'), 'dev')
            self.assertEqual(version.get_package_version('simo', default='x'), 'x')

    def test_get_package_version_falls_back_on_unexpected_error(self):
        from simo.core.utils import version

        with mock.patch.object(version.metadata, 'version', side_effect=RuntimeError('boom')):
            self.assertEqual(version.get_package_version('simo'), 'dev')

    def test_get_simo_version_delegates_to_get_package_version(self):
        from simo.core.utils import version

        with mock.patch.object(version, 'get_package_version', return_value='9.9.9') as gp:
            self.assertEqual(version.get_simo_version(), '9.9.9')
        gp.assert_called_once_with('simo', default='dev')
