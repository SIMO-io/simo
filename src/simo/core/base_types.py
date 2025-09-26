"""
Component base types as first-class, self-describing classes.

Apps can define their base types in their own `<app>.base_types` module
by subclassing `BaseComponentType`. For backward compatibility, each
module should also export a `BASE_TYPES` mapping `{slug: name}`; this
file exports such mapping automatically from declared classes.
"""

from abc import ABC
from django.utils.translation import gettext_lazy as _


class BaseComponentType(ABC):
    """Abstract base for component base types.

    Subclasses should set:
    - slug: string identifier stored in Component.base_type
    - name: human-friendly name (lazy-translated)
    - description: short explanation of what this type represents
    - purpose: when/why to use this type
    - required_methods: tuple of controller method names that must be
      implemented by controllers of this base type (optional).
    """

    slug: str = ''
    name: str = ''
    description: str = ''
    purpose: str = ''
    required_methods: tuple = tuple()

    @classmethod
    def describe(cls) -> dict:
        return {
            'slug': cls.slug,
            'name': cls.name,
            'description': cls.description,
            'purpose': cls.purpose,
            'required_methods': list(cls.required_methods or ()),
        }

    @classmethod
    def validate_controller(cls, controller_cls):
        """Validate that a controller satisfies this type's contract.

        Raises TypeError with a helpful message on mismatch.
        """
        # If there are no explicit requirements, nothing to validate.
        if not cls.required_methods:
            return

        missing = []
        for method in cls.required_methods:
            attr = getattr(controller_cls, method, None)
            if not callable(attr):
                missing.append(method)
        if missing:
            reqs = ', '.join(cls.required_methods)
            raise TypeError(
                f"Controller {controller_cls.__module__}.{controller_cls.__name__} "
                f"for base type '{cls.slug}' is missing required method(s): "
                f"{', '.join(missing)}. Expected: {reqs}"
            )


# ---- Core base types -------------------------------------------------


class NumericSensorType(BaseComponentType):
    slug = 'numeric-sensor'
    name = _("Numeric sensor")
    description = _("Represents a single numeric value that changes over time.")
    purpose = _("Use for temperature, humidity, light level, etc.")


class MultiSensorType(BaseComponentType):
    slug = 'multi-sensor'
    name = _("Multi sensor")
    description = _("Represents several labeled readings in one component.")
    purpose = _("Use when a single device reports multiple values.")


class BinarySensorType(BaseComponentType):
    slug = 'binary-sensor'
    name = _("Binary sensor")
    description = _("A boolean on/off style sensor.")
    purpose = _("Use for motion, door, presence, and similar states.")


class ButtonType(BaseComponentType):
    slug = 'button'
    name = _("Button")
    description = _("Momentary button events like click, double-click, hold.")
    purpose = _("Use to model input-only button devices.")


class SwitchType(BaseComponentType):
    slug = 'switch'
    name = _("Switch")
    description = _("Binary on/off actuator.")
    purpose = _("Use to control relays, power sockets, or generic toggles.")
    required_methods = ('turn_on', 'turn_off', 'toggle')


class DoubleSwitchType(BaseComponentType):
    slug = 'switch-double'
    name = _("Switch Double")
    description = _("Two-channel on/off actuator.")
    purpose = _("Use to control two separate loads in one device.")


class TripleSwitchType(BaseComponentType):
    slug = 'switch-triple'
    name = _("Switch Triple")
    description = _("Three-channel on/off actuator.")
    purpose = _("Use to control three separate loads in one device.")


class QuadrupleSwitchType(BaseComponentType):
    slug = 'switch-quadruple'
    name = _("Switch Quadruple")
    description = _("Four-channel on/off actuator.")
    purpose = _("Use to control four loads in one device.")


class QuintupleSwitchType(BaseComponentType):
    slug = 'switch-quintuple'
    name = _("Switch Quintuple")
    description = _("Five-channel on/off actuator.")
    purpose = _("Use to control five loads in one device.")


class DimmerType(BaseComponentType):
    slug = 'dimmer'
    name = _("Dimmer")
    description = _("Continuous actuator with settable output level.")
    purpose = _("Use to control lights or devices with variable output.")
    required_methods = ('turn_on', 'turn_off', 'toggle', 'output_percent', 'max_out')


class DimmerPlusType(BaseComponentType):
    slug = 'dimmer-plus'
    name = _("Dimmer Plus")
    description = _("Multi-channel dimmer with main and secondary outputs.")
    purpose = _("Use for fixtures with multiple dimmable channels.")


class RGBWLightType(BaseComponentType):
    slug = 'rgbw-light'
    name = _("RGB(W) light")
    description = _("Color-capable light with optional white channel.")
    purpose = _("Use for RGB/RGBW lighting control.")
    required_methods = ('turn_on', 'turn_off', 'toggle')


class LockType(BaseComponentType):
    slug = 'lock'
    name = _("Lock")
    description = _("Door lock actuator with state reporting.")
    purpose = _("Use to control smart locks and display their status.")
    required_methods = ('lock', 'unlock')


class GateType(BaseComponentType):
    slug = 'gate'
    name = _("Gate")
    description = _("Gate/door opener with open/close/call commands.")
    purpose = _("Use to manage gates with impulse or directional control.")
    required_methods = ('open', 'close', 'call')


class BlindsType(BaseComponentType):
    slug = 'blinds'
    name = _("Blinds")
    description = _("Window coverings with position and optional angle control.")
    purpose = _("Use to control roller blinds, shades, or venetians.")
    required_methods = ('open', 'close', 'stop')


def _export_base_types_dict():
    """Derive legacy BASE_TYPES mapping from declared classes.

    Returns {slug: name} for compatibility with legacy loaders.
    """
    import inspect as _inspect
    mapping = {}
    g = globals()
    for _name, _obj in g.items():
        if _inspect.isclass(_obj) and issubclass(_obj, BaseComponentType) \
                and _obj is not BaseComponentType and getattr(_obj, 'slug', None):
            mapping[_obj.slug] = _obj.name
    return mapping


# Backwards-compatible export for code still expecting a dict.
BASE_TYPES = _export_base_types_dict()
