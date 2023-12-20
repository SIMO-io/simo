from django.conf.urls import url
from .sso_views import LoginView, AuthenticateView


urlpatterns = [
    url(r'^$', LoginView.as_view(), name='login'),
    url(r'^authenticate/$', AuthenticateView.as_view(), name='simple-sso-authenticate'),
]
