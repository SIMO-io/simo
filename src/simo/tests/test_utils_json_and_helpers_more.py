from __future__ import annotations

import string

from django.test import SimpleTestCase


class TestRestoreJson(SimpleTestCase):
    pass


def _mk_restore_json_test(value, expected):
    from simo.core.utils.json import restore_json

    def _test(self):
        self.assertEqual(restore_json({'v': value})['v'], expected)

    return _test


_RESTORE_JSON_CASES = [
    ('0', 0),
    ('1', 1),
    ('-1', -1),
    ('0001', 1),
    ('42', 42),
    (' 7', 7),
    ('7 ', 7),
    ('+9', 9),
    ('2147483647', 2147483647),
    ('-2147483648', -2147483648),
    ('0.0', 0.0),
    ('1.0', 1.0),
    ('-1.5', -1.5),
    ('3.14159', 3.14159),
    (' 2.5', 2.5),
    ('2.5 ', 2.5),
    ('1e3', 1000.0),
    ('-1e2', -100.0),
    ('true', True),
    ('TRUE', True),
    ('false', False),
    ('FaLsE', False),
    ('', ''),
    ('hello', 'hello'),
    ('0x10', '0x10'),
    ('01.0.0', '01.0.0'),
    ('null', 'null'),
    (None, None),
    (True, True),
    (False, False),
    (123, 123),
    (12.5, 12.5),
]

for idx, (value, expected) in enumerate(_RESTORE_JSON_CASES):
    setattr(
        TestRestoreJson,
        f'test_restore_json_case_{idx}',
        _mk_restore_json_test(value, expected),
    )


class TestCoreHelpers(SimpleTestCase):
    pass


def _mk_is_hex_color_test(value, expected):
    from simo.core.utils.helpers import is_hex_color

    def _test(self):
        self.assertEqual(is_hex_color(value), expected)

    return _test


_HEX_COLOR_CASES = [
    ('#000000', True),
    ('#ffffff', True),
    ('#FFFFFF', True),
    ('#123456', True),
    ('#abcdef', True),
    ('#ABCDEF', True),
    ('#00000000', True),
    ('#FFFFFFFF', True),
    ('#01020304', True),
    ('000000', False),
    ('#000', False),
    ('#0000', False),
    ('#00000', False),
    ('#0000000', False),
    ('#000000000', False),
    ('#GGGGGG', False),
    ('#12345G', False),
    ('#12345', False),
    ('#1234567', False),
    ('#123456789', False),
    ('# 000000', False),
    (' #000000', False),
    ('', False),
]

for idx, (value, expected) in enumerate(_HEX_COLOR_CASES):
    setattr(
        TestCoreHelpers,
        f'test_is_hex_color_case_{idx}',
        _mk_is_hex_color_test(value, expected),
    )


class TestCoreHelpersBasic(SimpleTestCase):
    def test_get_random_string_length_and_charset(self):
        from simo.core.utils.helpers import get_random_string

        value = get_random_string(64)
        self.assertEqual(len(value), 64)
        allowed = set(string.ascii_uppercase + string.ascii_lowercase + string.digits)
        self.assertTrue(set(value).issubset(allowed))

    def test_get_client_ip_prefers_x_forwarded_for(self):
        from simo.core.utils.helpers import get_client_ip

        class Req:
            META = {
                'HTTP_X_FORWARDED_FOR': '10.0.0.1, 10.0.0.2',
                'REMOTE_ADDR': '127.0.0.1',
            }

        self.assertEqual(get_client_ip(Req()), '10.0.0.1')

    def test_get_client_ip_fallback_remote_addr(self):
        from simo.core.utils.helpers import get_client_ip

        class Req:
            META = {'REMOTE_ADDR': '10.0.0.5'}

        self.assertEqual(get_client_ip(Req()), '10.0.0.5')

