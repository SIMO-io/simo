from django.utils.translation import gettext_lazy as _
from simo.core.base_types import BaseComponentType


class AudioPlayerType(BaseComponentType):
    slug = 'audio-player'
    name = _("Audio Player")
    description = _("Playback control for audio sources.")
    purpose = _("Use to play/pause/stop audio and adjust playback.")
    required_methods = ('play', 'pause', 'stop')


class VideoPlayerType(BaseComponentType):
    slug = 'video-player'
    name = _("Video Player")
    description = _("Playback control for video sources.")
    purpose = _("Use to control video playback in the app.")
    required_methods = ('play', 'pause', 'stop')


def _export_base_types_dict():
    import inspect as _inspect
    mapping = {}
    for _name, _obj in globals().items():
        if _inspect.isclass(_obj) and issubclass(_obj, BaseComponentType) \
                and _obj is not BaseComponentType and getattr(_obj, 'slug', None):
            mapping[_obj.slug] = _obj.name
    return mapping


BASE_TYPES = _export_base_types_dict()
