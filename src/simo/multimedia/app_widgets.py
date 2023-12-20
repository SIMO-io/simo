from django.utils.translation import gettext_lazy as _
from simo.core.app_widgets import BaseAppWidget


class AudioPlayerWidget(BaseAppWidget):
    uid = 'audio-player'
    name = _('Audio Player')
    size = [2, 2]


class VideoPlayerWidget(BaseAppWidget):
    uid = 'video-player'
    name = _('Video Player')
    size = [4, 2]
