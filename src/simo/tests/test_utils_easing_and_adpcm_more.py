from __future__ import annotations

from django.test import SimpleTestCase


class TestEasingFunctions(SimpleTestCase):
    pass


def _mk_easing_range_test(func_name: str, t: float):
    from simo.core.utils import easing

    func = getattr(easing, func_name)

    def _test(self):
        value = func(t)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    return _test


_EASING_FUNCTIONS = [
    'easeInSine',
    'easeOutSine',
    'easeInOutSine',
    'easeInCubic',
    'easeOutCubic',
    'easeInOutCubic',
    'easeInQuint',
    'easeOutQuint',
    'easeInOutQuint',
    'easeInCirc',
    'easeOutCirc',
    'easeInOutCirc',
]

_T_VALUES = [round(i / 20, 2) for i in range(0, 21)]

for func_name in _EASING_FUNCTIONS:
    for idx, t in enumerate(_T_VALUES):
        setattr(
            TestEasingFunctions,
            f'test_{func_name}_range_{idx}',
            _mk_easing_range_test(func_name, t),
        )


class TestEasingSanity(SimpleTestCase):
    def test_ease_in_out_midpoints(self):
        from simo.core.utils.easing import (
            easeInOutSine,
            easeInOutCubic,
            easeInOutQuint,
            easeInOutCirc,
        )

        self.assertAlmostEqual(easeInOutSine(0.5), 0.5)
        self.assertAlmostEqual(easeInOutCubic(0.5), 0.5)
        self.assertAlmostEqual(easeInOutQuint(0.5), 0.5)
        self.assertAlmostEqual(easeInOutCirc(0.5), 0.5)

    def test_easing_choices_contains_known_entries(self):
        from simo.core.utils.easing import EASING_CHOICES

        keys = {key for key, _ in EASING_CHOICES}
        self.assertIn('linear', keys)
        self.assertIn('easeInSine', keys)
        self.assertIn('easeOutCirc', keys)
        self.assertIn('easeInOutQuint', keys)


class TestAdpcmCodec(SimpleTestCase):
    def test_self_test_reasonable_error(self):
        from simo.core.utils.adpcm4 import self_test

        max_err = self_test()
        self.assertLess(max_err, 2000)

    def test_encode_empty_returns_empty(self):
        from simo.core.utils.adpcm4 import encode

        self.assertEqual(encode(b''), b'')

    def test_decode_empty_returns_empty(self):
        from simo.core.utils.adpcm4 import decode

        self.assertEqual(decode(b''), b'')

    def test_encode_rejects_odd_length_pcm(self):
        from simo.core.utils.adpcm4 import encode

        with self.assertRaises(ValueError):
            encode(b'\x00')

    def test_encode_rejects_too_small_output_buffer(self):
        from simo.core.utils.adpcm4 import encode

        pcm = b'\x00\x00' * 4
        with self.assertRaises(ValueError):
            encode(pcm, out=bytearray(1))

    def test_decode_rejects_too_small_output_buffer(self):
        from simo.core.utils.adpcm4 import decode

        with self.assertRaises(ValueError):
            decode(b'\x00', out=bytearray(1))

    def test_decode_rejects_too_many_samples(self):
        from simo.core.utils.adpcm4 import decode

        with self.assertRaises(ValueError):
            decode(b'\x00', samples=3)

    def test_roundtrip_produces_same_length(self):
        from simo.core.utils.adpcm4 import ImaAdpcmState, decode, encode

        pcm = bytearray()
        for sample in [0, 100, -100, 2000, -2000, 32767, -32768]:
            pcm.append(sample & 0xFF)
            pcm.append((sample >> 8) & 0xFF)
        state = ImaAdpcmState()
        encoded = encode(pcm, state)
        decoded = decode(encoded, ImaAdpcmState(), samples=len(pcm) // 2)
        self.assertEqual(len(decoded), len(pcm))

