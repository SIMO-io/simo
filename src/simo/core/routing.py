from django.urls import re_path

from .socket_consumers import (
    LogConsumer, GatewayController, ComponentController,
)

urlpatterns = [
    re_path(r'ws/log/(?P<ct_id>\d+)/(?P<object_pk>\d+)/$', LogConsumer.as_asgi()),
    re_path(r'ws/gateway-controller/(?P<gateway_id>\d+)/$',
            GatewayController.as_asgi(), name='ws-gateway-controller'),
    re_path(r'ws/component-controller/(?P<component_id>\d+)/$',
            ComponentController.as_asgi(), name='ws-component-controller'),
]

