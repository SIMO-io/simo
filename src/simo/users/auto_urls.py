from django.conf.urls import include, url
from django.views.generic import TemplateView
from .views import accept_invitation

urlpatterns = [
    url(
        r"^accept-invitation/(?P<token>[a-zA-Z0-9]+)/$",
        accept_invitation, name='accept_invitation'
    ),
]
