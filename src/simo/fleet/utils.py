GPIO_PIN_DEFAULTS = {
    'output': True, 'input': True, 'default_pull': 'FLOATING',
    'native': True, 'adc': False,
    'capacitive': False, 'note': ''
}

BASE_ESP32_GPIO_PINS = {
    0: {
        'capacitive': True, 'adc': True,
        'default_pull': 'HIGH', 'note': "outputs PWM signal at boot"
    },
    1: {
        'input': False, 'note': "TX pin, debug output at boot"
    },
    2: {
        'capacitive': True, 'note': "on-board LED", 'adc': True
    },
    3: {
        'input': False, 'note': 'RX pin, HIGH at boot'
    },
    4: {
        'capacitive': True, 'adc': True
    },
    5: {
        'note': "outputs PWM signal at boot"
    },
    12: {
        'capacitive': True, 'adc': True,
        'note': "boot fail if pulled HIGH"
    },
    13: {
        'capacitive': True, 'adc': True
    },
    14: {
        'capacitive': True, 'adc': True,
        'note': "outputs PWM signal at boot",
    },
    15: {
        'capacitive': True, 'adc': True,
        'note': "outputs PWM signal at boot",
    },
    16: {}, 17: {}, 18: {}, 19: {}, 21: {}, 22: {}, 23: {},
    25: {'adc': True},
    26: {'adc': True},
    27: {'capacitive': True, 'adc': True},
    32: {'capacitive': True, 'adc': True},
    33: {'capacitive': True, 'adc': True},
    34: {'output': False, 'adc': True},
    35: {'output': False, 'adc': True},
    36: {'output': False, 'adc': True},
    39: {'output': False, 'adc': True},
}

GPIO_PINS = {'generic': {}, 'wESP32': {}, '4-relays': {}, 'ample-wall': {}}

for no, data in BASE_ESP32_GPIO_PINS.items():
    GPIO_PINS['generic'][no] = GPIO_PIN_DEFAULTS.copy()

#wESP32 & ample-wall
for no, data in BASE_ESP32_GPIO_PINS.items():
    if no in (16, 17, 19, 21, 22, 23, 25, 26, 27):
        # occupied by LAN
        continue

    if no == 2:
        # onboard LED
        continue

    GPIO_PINS['wESP32'][no] = GPIO_PIN_DEFAULTS.copy()
    GPIO_PINS['wESP32'][no].update(data)

    GPIO_PINS['ample-wall'][no] = GPIO_PIN_DEFAULTS.copy()
    GPIO_PINS['ample-wall'][no].update(data)


for no in range(101, 126):
    GPIO_PINS['ample-wall'][no] = {
        'output': True, 'input': True, 'default_pull': 'LOW',
        'native': False, 'adc': False,
        'capacitive': False, 'note': ''
    }
for no in range(126, 133):
    GPIO_PINS['ample-wall'][no] = {
        'output': True, 'input': True, 'default_pull': 'HIGH',
        'native': False, 'adc': False,
        'capacitive': False, 'note': ''
    }


#4-relays
for no, data in BASE_ESP32_GPIO_PINS.items():
    if no == 12:
        # occupied by control button
        continue
    if no == 4:
        # occupied by onboard LED
        continue
    if no in (13, 15):
        # occupied by RS485 chip
        continue
    GPIO_PINS['4-relays'][no] = GPIO_PIN_DEFAULTS.copy()
    if no == 25:
        GPIO_PINS['4-relays'][no]['input'] = False
        GPIO_PINS['4-relays'][no]['note'] = 'Relay1'
    elif no == 26:
        GPIO_PINS['4-relays'][no]['input'] = False
        GPIO_PINS['4-relays'][no]['note'] = 'Relay2'
    elif no == 27:
        GPIO_PINS['4-relays'][no]['input'] = False
        GPIO_PINS['4-relays'][no]['note'] = 'Relay3'
    elif no == 14:
        GPIO_PINS['4-relays'][no]['input'] = False
        GPIO_PINS['4-relays'][no]['note'] = 'Relay4'
    else:
        GPIO_PINS['4-relays'][no].update(data)


def get_available_gpio_pins(colonel=None, filters=None, selected=None):
    if not colonel:
        return {no: GPIO_PIN_DEFAULTS for no in range(200)}
    if not filters:
        filters = {}
    pins = {}
    allow_occupied = filters.pop('allow_occupied', None)
    for key, data in GPIO_PINS.get(colonel.type, {}).items():
        if str(key) in colonel.occupied_pins and not allow_occupied:
            if selected:
                if int(key) != int(selected):
                    continue
            else:
                continue
        skip = False
        for filter_param, filter_val in filters.items():
            if data[filter_param] != filter_val:
                skip = True
        if skip:
            continue
        pins[key] = data
    return pins


def get_gpio_pins_choices(colonel=None, filters=None, selected=None):
    choices = []
    for key, data in get_available_gpio_pins(
        colonel, filters, selected
    ).items():
        if key < 100:
            name = 'GPIO%d' % key
        else:
            name = 'E-%d' % (key - 100)
        if data.get('note'):
            name += ' | %s' % data['note']
        choices.append((key, name))
    return choices
