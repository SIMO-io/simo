from django.urls import path, re_path
from .views import SoundAutocomplete


urlpatterns = [
    path(
        'autocomplete-sound',
        SoundAutocomplete.as_view(), name='autocomplete-sound'
    )
]
