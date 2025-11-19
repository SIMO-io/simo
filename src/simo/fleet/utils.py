from django.db import transaction, models
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
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

        if no in (13, 23, 32, 33):
            GPIO_PINS['game-changer-mini'][no] = GPIO_PIN_DEFAULTS.copy()
            GPIO_PINS['game-changer-mini'][no].update(data)


for no in range(101, 126):
    GPIO_PINS['ample-wall'][no] = {
        'output': True, 'input': True, 'default_pull': 'LOW',
        'native': False, 'adc': False,
        'capacitive': False, 'note': ''
    }
    if no in (101, 102):
        GPIO_PINS['ample-wall'][no]['interface'] = no - 100

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
    if no in (101, 102):
        GPIO_PINS['game-changer'][no]['interface'] = no - 100

for no in range(101, 105):
    GPIO_PINS['game-changer-mini'][no] = {
        'output': True, 'input': True, 'default_pull': 'LOW',
        'native': False, 'adc': False,
        'capacitive': False, 'note': ''
    }
    if no in (101, 102):
        GPIO_PINS['game-changer-mini'][no]['interface'] = no - 100


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


def get_i2c_interface_no(config):
    interface_no = config.get('interface_no')
    if interface_no is not None:
        return interface_no

    interface_id = config.get('i2c_interface')
    if not interface_id:
        return None
    try:
        interface_id = int(interface_id)
    except (TypeError, ValueError):
        return None

    from .models import Interface  # local import to avoid circular deps

    interface = Interface.objects.filter(id=interface_id).first()
    if interface:
        return interface.no
    return None


def _get_component_interface_addresses(component):
    """Return list[(interface_id, address_type, address)] component needs.

    Supports I²C and DALI controllers. Extend when new bus types land.
    """
    from .models import Interface  # local import to avoid circular deps

    cfg = component.config or {}
    desired = []

    # I²C ----------------------------------------------------------------
    if 'i2c_interface' in cfg and 'i2c_address' in cfg:
        desired.append((cfg['i2c_interface'], 'i2c', cfg['i2c_address']))

    # DALI ---------------------------------------------------------------
    interface_no = None
    if 'dali_interface' in cfg:
        interface_no = cfg['dali_interface']
    elif 'interface' in cfg:
        interface_no = cfg['interface']

    if interface_no is not None and 'colonel' in cfg and 'da' in cfg:
        interface_obj = Interface.objects.filter(
            colonel_id=cfg['colonel'], no=interface_no
        ).first()
        if interface_obj:
            uid = component.controller_uid or ''
            if uid.endswith('DALIGearGroup'):
                addr_type = 'dali-group'
            elif uid.endswith(('DALILamp', 'DALIRelay')):
                addr_type = 'dali-gear'
            else:
                addr_type = 'dali-device'
            desired.append((interface_obj.id, addr_type, cfg['da']))

    return desired


def _sync_interface_address_occupancy(component):
    """Synchronise InterfaceAddress rows for *component* (claim/release)."""
    from .models import InterfaceAddress  # local import, avoids circulars

    desired = set(_get_component_interface_addresses(component))

    # Short-circuit if nothing desired and nothing currently occupied.
    if not desired and not InterfaceAddress.objects.filter(
        occupied_by_id=component.id,
        occupied_by_content_type=ContentType.objects.get_for_model(component),
    ).exists():
        return

    with transaction.atomic():
        ct = ContentType.objects.get_for_model(component)

        iface_ids = [d[0] for d in desired]
        lock_qs = InterfaceAddress.objects.select_for_update().filter(
            models.Q(occupied_by_content_type=ct, occupied_by_id=component.id)
            | models.Q(interface_id__in=iface_ids)
        )

        addr_map = {(
            ia.interface_id, ia.address_type, ia.address): ia for ia in lock_qs}

        # Release obsolete ------------------------------------------------
        for ia in lock_qs:
            key = (ia.interface_id, ia.address_type, ia.address)
            if ia.occupied_by_id == component.id and key not in desired:
                ia.occupied_by = None

        # Claim desired ---------------------------------------------------
        for iface_id, addr_type, addr_val in desired:
            key = (iface_id, addr_type, addr_val)
            ia = addr_map.get(key)
            if not ia:
                ia = InterfaceAddress.objects.select_for_update().create(
                    interface_id=iface_id, address_type=addr_type,
                    address=addr_val,
                )
                addr_map[key] = ia
            if ia.occupied_by and ia.occupied_by != component:
                raise ValidationError(
                    f"Interface address {ia} already occupied by "
                    f"{ia.occupied_by}."
                )
            ia.occupied_by = component

        # Bulk save all modified objects
        InterfaceAddress.objects.bulk_update(
            addr_map.values(),
            ["occupied_by_content_type", "occupied_by_id"],
        )


def _release_interface_addresses(component):
    """Clear all InterfaceAddress rows owned by component."""
    from .models import InterfaceAddress  # delayed import

    ct = ContentType.objects.get_for_model(component)
    with transaction.atomic():
        addresses = InterfaceAddress.objects.select_for_update().filter(
            occupied_by_content_type=ct, occupied_by_id=component.id,
        )
        if not addresses:
            return
        for ia in addresses:
            ia.occupied_by = None
        InterfaceAddress.objects.bulk_update(
            addresses, ["occupied_by_content_type", "occupied_by_id"]
        )


def get_all_control_input_choices():
    '''
    This is called multiple times by component form,
    so we cache the data to speed things up!
    '''
    # TODO: filter by instance!
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
