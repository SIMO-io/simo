from django.urls import path, re_path
from .views import (
    colonels_ping,
    PinsSelectAutocomplete,
    InterfaceSelectAutocomplete,
    ControlInputSelectAutocomplete
)

urlpatterns = [
    re_path(
        r"^colonels-ping/$", colonels_ping, name='colonels-ping'
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
