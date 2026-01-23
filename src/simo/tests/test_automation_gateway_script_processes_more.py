import os
import sys
from unittest import mock

from django.test import override_settings

from .base import BaseSimoTestCase


class ScriptMultiprocessingContextTests(BaseSimoTestCase):
    def test_script_process_context_defaults_to_spawn(self):
        from simo.automation import gateways

        with mock.patch.dict(os.environ, {}, clear=True):
            with override_settings(SCRIPT_START_METHOD=None):
                ctx = gateways._get_script_multiprocessing_context()
        self.assertEqual(ctx.get_start_method(), 'spawn')

    def test_script_process_context_respects_env_override(self):
        if sys.platform.startswith('win'):
            self.skipTest("Windows does not support 'fork' start method")

        from simo.automation import gateways

        with mock.patch.dict(os.environ, {'SIMO_SCRIPT_START_METHOD': 'fork'}):
            ctx = gateways._get_script_multiprocessing_context()
        self.assertEqual(ctx.get_start_method(), 'fork')

