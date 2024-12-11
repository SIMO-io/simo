from django.urls import path
from .views import (
    get_timestamp, upgrade, restart, reboot, set_instance, delete_instance
)
from .autocomplete_views import (
    IconModelAutocomplete,
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
    path('set-instance/<slug:instance_slug>/', set_instance, name='set-instance'),
    path('upgrade/', upgrade, name='upgrade'),
    path('restart/', restart, name='restart'),
    path('reboot/', reboot, name='reboot'),
    path('delete-instance/', delete_instance, name='delete-instance')
]
