from unittest import mock

from django.test import SimpleTestCase, override_settings


class VirtualAutomationsHookTests(SimpleTestCase):
    @override_settings(IS_VIRTUAL=True, VIRTUAL_AUTOMATIONS_APP='jailed_automations')
    def test_virtual_scripts_managed_externally_checks_app_install(self):
        from simo.automation import gateways as gw_mod

        with mock.patch.object(gw_mod.apps, 'is_installed', autospec=True, return_value=True):
            self.assertTrue(gw_mod._virtual_scripts_managed_externally())
        with mock.patch.object(gw_mod.apps, 'is_installed', autospec=True, return_value=False):
            self.assertFalse(gw_mod._virtual_scripts_managed_externally())

