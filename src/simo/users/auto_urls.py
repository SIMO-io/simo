from django.urls import include, re_path
from django.views.generic import TemplateView
from .views import accept_invitation

urlpatterns = [
    re_path(
        r"^accept-invitation/(?P<token>[a-zA-Z0-9]+)/$",
        accept_invitation, name='accept_invitation'
    ),
]
