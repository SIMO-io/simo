import struct


BLE_DEVICE_TYPE_GOVEE_MULTISENSOR = 1

_ADV_TYPE_FLAGS = 0x01
_ADV_TYPE_NAME = 0x09
_ADV_TYPE_UUID16_COMPLETE = 0x3
_ADV_TYPE_UUID32_COMPLETE = 0x5
_ADV_TYPE_UUID128_COMPLETE = 0x7
_ADV_TYPE_UUID16_MORE = 0x2
_ADV_TYPE_UUID32_MORE = 0x4
_ADV_TYPE_UUID128_MORE = 0x6
_ADV_TYPE_APPEARANCE = 0x19
GAP_MFG_DATA = 0xFF


def decode_field(payload, adv_type):
    i = 0
    result = []
    while i + 1 < len(payload):
        if payload[i + 1] == adv_type:
            result.append(payload[i + 2 : i + payload[i] + 1])
        i += 1 + payload[i]
    return result


def decode_name(payload):
    n = decode_field(payload, _ADV_TYPE_NAME)
    return str(n[0], "utf-8") if n else ""


def decode_services(payload):
    services = []
    for u in decode_field(payload, _ADV_TYPE_UUID16_COMPLETE):
        services.append(struct.unpack("<H", u)[0])
    for u in decode_field(payload, _ADV_TYPE_UUID32_COMPLETE):
        services.append(struct.unpack("<d", u)[0])
    for u in decode_field(payload, _ADV_TYPE_UUID128_COMPLETE):
        services.append(u)
    return services
