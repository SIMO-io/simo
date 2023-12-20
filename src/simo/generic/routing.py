from django.urls import re_path

from .socket_consumers import CamStreamConsumer

urlpatterns = [
    re_path(
        r'ws/cam-stream/(?P<component_id>\d+)/$', CamStreamConsumer.as_asgi(),
        name='ws-cam-stream'
    ),
]
