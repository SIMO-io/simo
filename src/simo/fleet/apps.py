from django.apps import AppConfig


class SIMOFleetAppConfig(AppConfig):
    name = 'simo.fleet'

    def ready(self):
        from actstream import registry
        from simo.fleet.models import Colonel
        registry.register(Colonel)