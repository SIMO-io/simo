import importlib, importlib.util, datetime, sys, traceback
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

    module_path = f"{app.name}.routing"

    # Only attempt import if the module exists
    spec = importlib.util.find_spec(module_path)
    if spec is None:
        continue

    # Import and collect urlpatterns; on failure, print full traceback and continue
    try:
        routing = importlib.import_module(module_path)
    except Exception:
        print(
            f"Failed to import {module_path}:\n{traceback.format_exc()}"
        )
        continue

    try:
        app_urlpatterns = getattr(routing, 'urlpatterns', None)
        if isinstance(app_urlpatterns, list):
            urlpatterns.extend(app_urlpatterns)
    except Exception:
        print(
            f"Error while processing urlpatterns from {module_path}:\n{traceback.format_exc()}"
        )
        continue


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
