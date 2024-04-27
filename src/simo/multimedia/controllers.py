from django.utils.translation import gettext_lazy as _
from simo.core.controllers import Switch, TimerMixin
from .app_widgets import AudioPlayerWidget, VideoPlayerWidget


class BasePlayer(Switch):
    default_config = {
        'has_volume_control': True,
    }
    default_meta = {
        'volume': 50,
        'shuffle': False,
        'loop': False,
        'has_next': False,
        'has_previous': False,
        'duration': None,
        'position': None,
        'title': None,
        'library': []
    }
    default_value = 'stopped'

    def _prepare_for_send(self, value):
        if isinstance(value, bool):
            if value:
                return 'play'
            return 'pause'
        return value

    def _validate_val(self, value, occasion=None):
        return value

    def play(self):
        self.send('play')

    def pause(self):
        self.send('pause')

    def stop(self):
        self.send('stop')

    def seek(self, second):
        self.send({'seek': second})

    def next(self):
        self.send('next')

    def previous(self):
        self.send('previous')

    def set_volume(self, val):
        assert 0 <= val <= 100
        self.send({'set_volume': val})

    def get_volume(self):
        return self.component.meta['volume']

    def set_shuffle_play(self, val):
        self.send({'shuffle': bool(val)})

    def set_loop_play(self, val):
        self.send({'loop': bool(val)})

    def play_library_item(self, val):
        self.send({'play_from_library': val})

    def toggle(self):
        if self.component.value == 'playing':
            self.turn_off()
        else:
            self.turn_on()


class BaseAudioPlayer(BasePlayer):
    """Base class for audio players"""
    name = _("Audio Player")
    base_type = 'audio-player'
    app_widget = AudioPlayerWidget


class BaseVideoPlayer(BasePlayer):
    """Base class for video players"""
    name = _("Video Player")
    base_type = 'video-player'
    app_widget = VideoPlayerWidget
