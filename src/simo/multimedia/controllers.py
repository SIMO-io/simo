from django.utils.translation import gettext_lazy as _
from simo.core.controllers import Switch, TimerMixin
from .app_widgets import AudioPlayerWidget, VideoPlayerWidget


class BasePlayer(Switch):
    admin_widget_template = 'admin/controller_widgets/player.html'
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
        'image_url': None,
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
        self.component.meta['volume'] = val
        self.component.save()
        self.send({'set_volume': val})

    def get_volume(self):
        '''override of possible with something more reliable'''
        return self.component.meta['volume']

    def set_shuffle_play(self, val):
        self.component.meta['shuffle'] = bool(val)
        self.component.save()
        self.send({'shuffle': bool(val)})

    def set_loop_play(self, val):
        self.component.meta['loop'] = bool(val)
        self.component.save()
        self.send({'loop': bool(val)})

    def play_library_item(self, id, volume=None, fade_in=None):
        '''
        :param id: Library item ID
        :param volume: Volume to play at. Current volume will be used if not provided
        :param fade_in: number of seconds to fade in
        :return:
        '''
        self.send({'play_from_library': id, 'volume': volume, 'fade_in': fade_in})

    def play_uri(self, uri, volume=None):
        '''
        Replace que with this single uri and play it immediately
        :param uri: playable uri or url
        :param volume: volume at which to play
        :return:
        '''
        if volume:
            assert 0 <= volume <= 100
        self.send({"play_uri": uri, 'volume': volume})

    # def play_alert(self, val, loop=False, volume=None):
    #     '''
    #     Plays alert and goes back to whatever was playing initially
    #     :param val: uri
    #     :param loop: Repeat infinitely
    #     :param volume: volume at which to play
    #     :return:
    #     '''
    #     assert type(val) == str
    #     if volume:
    #         assert 0 <= volume <= 100
    #     self.send({"alert": val, 'loop': loop, 'volume': volume})


    def play_alert(self, id):
        self.send({"alert": id})

    def cancel_alert(self):
        '''Cancel alert if it's currently playing'''
        self.send({"alert": None})

    def toggle(self):
        if self.component.value == 'playing':
            self.pause()
        else:
            self.play()


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



