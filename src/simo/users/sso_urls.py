from django.urls import re_path
from .sso_views import LoginView, AuthenticateView


urlpatterns = [
    re_path(r'^$', LoginView.as_view(), name='login'),
    re_path(r'^authenticate/$', AuthenticateView.as_view(), name='simple-sso-authenticate'),
]
