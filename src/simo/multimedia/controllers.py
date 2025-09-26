from django.utils.translation import gettext_lazy as _
from simo.core.controllers import Switch, TimerMixin
from .app_widgets import AudioPlayerWidget, VideoPlayerWidget
from .base_types import AudioPlayerType, VideoPlayerType


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

    def send(self, value):
        """Control playback.

        Parameters:
        - value (str): one of 'play', 'pause', 'stop', 'next', 'previous', or
        - value (dict): one of {'seek': seconds}, {'set_volume': 0-100},
                        {'shuffle': bool}, {'loop': bool}, {'alert': id|None},
                        {'play_from_library': id, 'volume': int|None, 'fade_in': seconds|None},
                        {'play_uri': uri, 'volume': int|None}.
        Prefer using the convenience methods (`play()`, `pause()`, `seek()`, ...).
        """
        return super().send(value)

    def play(self):
        """Start or resume playback."""
        self.send('play')

    def pause(self):
        """Pause playback (keeps current position)."""
        self.send('pause')

    def stop(self):
        """Stop playback and reset position to start (if supported)."""
        self.send('stop')

    def seek(self, second):
        """Seek to the specified position in seconds.

        Parameters:
        - second (int|float): Absolute position from start.
        """
        self.send({'seek': second})

    def next(self):
        """Skip to the next item in the queue/playlist."""
        self.send('next')

    def previous(self):
        """Return to the previous item in the queue/playlist."""
        self.send('previous')

    def set_volume(self, val):
        """Set output volume.

        Parameters:
        - val (int): Volume percent 0–100.
        """
        assert 0 <= val <= 100
        self.component.meta['volume'] = val
        self.component.save()
        self.send({'set_volume': val})

    def get_volume(self):
        """Get the last known volume (0–100).

        Note: This reads cached meta; device may differ if gateway does not
        report volume changes.
        """
        return self.component.meta['volume']

    def set_shuffle_play(self, val):
        """Enable or disable shuffle mode.

        Parameters:
        - val (bool|int): Truthy to enable, falsy to disable.
        """
        self.component.meta['shuffle'] = bool(val)
        self.component.save()
        self.send({'shuffle': bool(val)})

    def set_loop_play(self, val):
        """Enable or disable loop/repeat mode.

        Parameters:
        - val (bool|int): Truthy to enable, falsy to disable.
        """
        self.component.meta['loop'] = bool(val)
        self.component.save()
        self.send({'loop': bool(val)})

    def play_library_item(self, id, volume=None, fade_in=None):
        """Play an item from the controller's library.

        Parameters:
        - id: Library item identifier as provided by the gateway.
        - volume (int|None): Optional volume 0–100; keep current if None.
        - fade_in (int|float|None): Optional seconds to fade in.
        """
        self.send({'play_from_library': id, 'volume': volume, 'fade_in': fade_in})

    def play_uri(self, uri, volume=None):
        """Replace the queue with a single URI and play immediately.

        Parameters:
        - uri (str): Playable URI/URL (e.g. file://, http://, spotify:...).
        - volume (int|None): Optional volume 0–100; keep current if None.
        """
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
        """Play a one-shot alert sound by id, then resume previous playback.

        Parameters:
        - id: Alert sound identifier.
        """
        self.send({"alert": id})

    def cancel_alert(self):
        """Cancel an in-progress alert and resume previous playback."""
        self.send({"alert": None})

    def toggle(self):
        """Toggle between play and pause based on current state."""
        if self.component.value == 'playing':
            self.pause()
        else:
            self.play()


class BaseAudioPlayer(BasePlayer):
    """Base class for audio players"""
    name = _("Audio Player")
    base_type = AudioPlayerType
    app_widget = AudioPlayerWidget


class BaseVideoPlayer(BasePlayer):
    """Base class for video players"""
    name = _("Video Player")
    base_type = VideoPlayerType
    app_widget = VideoPlayerWidget
