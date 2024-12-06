from django.urls import re_path, path
from .views import accept_invitation, RolesAutocomplete

urlpatterns = [
    re_path(
        r"^accept-invitation/(?P<token>[a-zA-Z0-9]+)/$",
        accept_invitation, name='accept_invitation'
    ),
    path(
        'autocomplete-roles',
        RolesAutocomplete.as_view(), name='autocomplete-user-roles'
    ),
]
