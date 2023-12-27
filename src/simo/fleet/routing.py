from django.urls import re_path

from .socket_consumers import FleetConsumer

urlpatterns = [
    re_path(r'ws/fleet/$', FleetConsumer.as_asgi()),
]
