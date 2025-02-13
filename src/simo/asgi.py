import importlib, datetime, sys
from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

from django.apps import apps

urlpatterns = []

for name, app in apps.app_configs.items():
    if name in (
        'auth', 'admin', 'contenttypes', 'sessions', 'messages',
        'staticfiles'
    ):
        continue
    try:
        routing = importlib.import_module('%s.routing' % app.name)
    except ModuleNotFoundError:
        continue
    for var_name, item in routing.__dict__.items():
        if isinstance(item, list) and var_name == 'urlpatterns':
            urlpatterns.extend(item)


class TimestampedStream:
    """Adds timestamps to all the prints"""

    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        if data != '\n':
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.stream.write(f'[{timestamp}] {data}')
        else:
            self.stream.write(data)

    def flush(self):
        self.stream.flush()


sys.stdout = TimestampedStream(sys.stdout)

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    'websocket': AuthMiddlewareStack(
        URLRouter(urlpatterns)
    ),
})
