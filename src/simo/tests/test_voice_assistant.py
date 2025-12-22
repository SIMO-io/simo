from django.test import TestCase


class VoiceAssistantUtilsTests(TestCase):
    def test_normalize_language(self):
        from simo.fleet.voice_assistant import _normalize_language

        self.assertIsNone(_normalize_language(None))
        self.assertIsNone(_normalize_language(''))
        self.assertEqual(_normalize_language('lt-LT'), 'lt')
        self.assertEqual(_normalize_language('lt_LT'), 'lt')
        self.assertEqual(_normalize_language('lt-LT,lt;q=0.9'), 'lt')
        self.assertEqual(_normalize_language(' EN-us '), 'en')

