from __future__ import annotations

from django.test import SimpleTestCase


class TestFleetBleDecoding(SimpleTestCase):
    def test_decode_name_returns_empty_when_missing(self):
        from simo.fleet.ble import decode_name

        self.assertEqual(decode_name(b''), '')

    def test_decode_name_decodes_utf8(self):
        from simo.fleet.ble import decode_name

        payload = bytes([4, 0x09, 0x41, 0x42, 0x43])
        self.assertEqual(decode_name(payload), 'ABC')

    def test_decode_field_extracts_multiple_fields(self):
        from simo.fleet.ble import decode_field

        payload = bytes(
            [
                4,
                0x09,
                0x41,
                0x42,
                0x43,
                3,
                0x09,
                0x78,
                0x79,
            ]
        )
        self.assertEqual(decode_field(payload, 0x09), [b'ABC', b'xy'])

    def test_decode_services_decodes_uuid16_uuid32_uuid128(self):
        from simo.fleet.ble import decode_services

        uuid16 = [3, 0x03, 0x0F, 0x18]  # 0x180F (Battery)
        uuid32 = [5, 0x05, 0x78, 0x56, 0x34, 0x12]  # 0x12345678
        uuid128_data = bytes(range(16))
        uuid128 = [17, 0x07, *uuid128_data]

        payload = bytes(uuid16 + uuid32 + uuid128)
        services = decode_services(payload)

        self.assertIn(0x180F, services)
        self.assertIn(0x12345678, services)
        self.assertIn(uuid128_data, services)

