from django.utils.translation import gettext_lazy as _
from simo.core.base_types import BaseComponentType


class DaliDeviceType(BaseComponentType):
    slug = 'dali'
    name = _("Dali Device")
    description = _("DALI bus device discovered and managed by Fleet.")
    purpose = _("Use for DALI-compliant gear integration.")


class RoomSensorType(BaseComponentType):
    slug = 'room-sensor'
    name = _("Room Sensor")
    description = _("Room environment sensor reporting readings.")
    purpose = _("Use to capture ambient conditions from Fleet devices.")


class VoiceAssistantType(BaseComponentType):
    slug = 'voice-assistant'
    name = _("Voice Assistant")
    description = _("SIMO AI smart home voice assistant.")
    purpose = _("Control smart home instance using voice commands.")



def _export_base_types_dict():
    import inspect as _inspect
    mapping = {}
    for _name, _obj in globals().items():
        if _inspect.isclass(_obj) and issubclass(_obj, BaseComponentType) \
                and _obj is not BaseComponentType and getattr(_obj, 'slug', None):
            mapping[_obj.slug] = _obj.name
    return mapping


BASE_TYPES = _export_base_types_dict()
