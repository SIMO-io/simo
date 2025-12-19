from django.urls import path, re_path
from .views import (
    colonels_ping,
    new_sentinel,
    ColonelsAutocomplete,
    PinsSelectAutocomplete,
    InterfaceSelectAutocomplete,
    ControlInputSelectAutocomplete
)

urlpatterns = [
    re_path(
        r"^colonels-ping/$", colonels_ping, name='colonels-ping'
    ),
    path('new-sentinel/', new_sentinel, name='new-sentinel'),
    path(
        'autocomplete-colonels',
        ColonelsAutocomplete.as_view(), name='autocomplete-colonels'
    ),
    path(
        'autocomplete-colonel-pins',
        PinsSelectAutocomplete.as_view(), name='autocomplete-colonel-pins'
    ),
    path(
        'autocomplete-colonel-interfaces',
        InterfaceSelectAutocomplete.as_view(),
        name='autocomplete-interfaces'
    ),
    path(
        'autocomplete-control-input',
        ControlInputSelectAutocomplete.as_view(),
        name='autocomplete-control_inputs'
    )
]
