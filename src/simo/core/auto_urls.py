from django.urls import path
from .views import get_timestamp, setup_wizard, update, restart, reboot
from .autocomplete_views import (
    IconModelAutocomplete, #IconSlugAutocomplete,
    CategoryAutocomplete, ZoneAutocomplete,
    ComponentAutocomplete,
)

urlpatterns = [
    path('timestamp/', get_timestamp),
    path(
        'autocomplete-icon',
        IconModelAutocomplete.as_view(), name='autocomplete-icon'
    ),
    # path(
    #     'autocomplete-icon-slug',
    #     IconSlugAutocomplete.as_view(), name='autocomplete-icon'
    # ),
    path(
        'autocomplete-category',
        CategoryAutocomplete.as_view(), name='autocomplete-category'
    ),
    path(
        'autocomplete-zone',
        ZoneAutocomplete.as_view(), name='autocomplete-zone'
    ),
    path(
        'autocomplete-component',
        ComponentAutocomplete.as_view(), name='autocomplete-component'
    ),
    path('setup/', setup_wizard, name='setup-wizard'),
    path('update/', update, name='update'),
    path('restart/', restart, name='restart'),
    path('reboot/', reboot, name='reboot')
]
