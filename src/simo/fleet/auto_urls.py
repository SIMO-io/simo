from django.urls import path, re_path
from django.views.generic import TemplateView
from .views import (
    colonels_ping,
    PinsSelectAutocomplete,
    I2CInterfaceSelectAutocomplete
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
        'autocomplete-colonel-i2c_interfaces',
        I2CInterfaceSelectAutocomplete.as_view(), name='autocomplete-colonel-i2c_interfaces'
    )
]
