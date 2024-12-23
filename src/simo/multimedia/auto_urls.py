from django.urls import path, re_path
from .views import SoundAutocomplete, sound_stream


urlpatterns = [
    path(
        'autocomplete-sound/',
        SoundAutocomplete.as_view(), name='autocomplete-sound'
    ),
    path(
        'sound-<int:sound_id>-stream/', sound_stream, name='sound-stream'
    )
]
