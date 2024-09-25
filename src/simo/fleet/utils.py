from simo.core.utils.cache import get_cached_data
from simo.core.middleware import get_current_instance

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

GPIO_PINS = {
    'generic': {}, '4-relays': {}, 'ample-wall': {},
    'game-changer': {}, 'game-changer-mini': {}
}

for no, data in BASE_ESP32_GPIO_PINS.items():
    GPIO_PINS['generic'][no] = GPIO_PIN_DEFAULTS.copy()

# ample-wall
for no, data in BASE_ESP32_GPIO_PINS.items():
    if no in (12, 13, 14, 23, 32, 33, 34, 36, 39):
        GPIO_PINS['ample-wall'][no] = GPIO_PIN_DEFAULTS.copy()
        GPIO_PINS['ample-wall'][no].update(data)

        GPIO_PINS['game-changer'][no] = GPIO_PIN_DEFAULTS.copy()
        GPIO_PINS['game-changer'][no].update(data)


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


for no in range(101, 139):
    GPIO_PINS['game-changer'][no] = {
        'output': True, 'input': True, 'default_pull': 'LOW',
        'native': False, 'adc': False,
        'capacitive': False, 'note': ''
    }

for no in range(101, 105):
    GPIO_PINS['game-changer-mini'][no] = {
        'output': True, 'input': True, 'default_pull': 'LOW',
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


INTERFACES_PINS_MAP = {
    1: [13, 23], 2: [32, 33]
}


def get_all_control_input_choices():
    '''
    This is called multiple times by component form,
    so we cache the data to speed things up!
    '''
    def get_control_input_choices():
        from .models import ColonelPin
        from simo.core.models import Component
        pins_qs = ColonelPin.objects.all()

        buttons_qs = Component.objects.filter(
            base_type='button'
        ).select_related('zone')

        return [(f'pin-{pin.id}', str(pin)) for pin in pins_qs] + \
               [(f'button-{button.id}',
                 f"{button.zone.name} | {button.name}"
                 if button.zone else button.name)
                for button in buttons_qs]

    instance = get_current_instance()

    return get_cached_data(
        f'{instance.id}-fleet-control-inputs', get_control_input_choices, 10
    )
