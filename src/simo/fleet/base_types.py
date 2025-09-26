from django.utils.translation import gettext_lazy as _
from simo.core.base_types import BaseComponentType


class DaliDeviceType(BaseComponentType):
    slug = 'dali'
    name = _("Dali Device")
    description = _("DALI bus device discovered and managed by Fleet.")
    purpose = _("Use for DALI-compliant gear integration.")


class SentinelType(BaseComponentType):
    slug = 'sentinel'
    name = _("Sentinel")
    description = _("Room environment sensor reporting readings, alarm siren, AI voice assistant.")
    purpose = _("Use to capture ambient conditions of a zone, raise alarms, provice AI voice assistant.")


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
