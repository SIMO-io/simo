from django.utils.translation import gettext_lazy as _
from simo.core.base_types import BaseComponentType


class ScriptType(BaseComponentType):
    slug = 'script'
    name = _("Script")
    description = _("Runs user-defined logic or actions.")
    purpose = _("Use for programmable behaviors or routines.")


class ThermostatType(BaseComponentType):
    slug = 'thermostat'
    name = _("Thermostat")
    description = _("Thermal control orchestrating heaters/coolers.")
    purpose = _("Use to maintain target temperature based on sensors.")


class AlarmGroupType(BaseComponentType):
    slug = 'alarm-group'
    name = _("Alarm Group")
    description = _("Aggregates security components into a single state.")
    purpose = _("Use to arm/disarm and observe overall security status.")
    required_methods = ('arm', 'disarm')


class IPCameraType(BaseComponentType):
    slug = 'ip-camera'
    name = _("IP Camera")
    description = _("Network camera streaming and snapshots.")
    purpose = _("Use to integrate RTSP-capable cameras.")


class WeatherType(BaseComponentType):
    slug = 'weather'
    name = _("Weather")
    description = _("Aggregated weather information for the instance.")
    purpose = _("Use to display external weather data.")


class WateringType(BaseComponentType):
    slug = 'watering'
    name = _("Watering")
    description = _("Irrigation control with programs and manual runs.")
    purpose = _("Use to drive valves/pumps for garden irrigation.")


class StateSelectType(BaseComponentType):
    slug = 'state-select'
    name = _("State Select")
    description = _("Pick one of predefined states.")
    purpose = _("Use to represent and switch between modes/states.")


class AlarmClockType(BaseComponentType):
    slug = 'alarm-clock'
    name = _("Alarm Clock")
    description = _("User-configurable alarm schedule and events.")
    purpose = _("Use to trigger actions at specific times.")


def _export_base_types_dict():
    import inspect as _inspect
    mapping = {}
    for _name, _obj in globals().items():
        if _inspect.isclass(_obj) and issubclass(_obj, BaseComponentType) \
                and _obj is not BaseComponentType and getattr(_obj, 'slug', None):
            mapping[_obj.slug] = _obj.name
    return mapping


BASE_TYPES = _export_base_types_dict()
