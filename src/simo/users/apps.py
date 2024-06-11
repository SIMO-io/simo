from django.apps import AppConfig


class SIMOUsersAppConfig(AppConfig):
    name = 'simo.users'

    def ready(self):
        from actstream import registry
        registry.register(self.get_model('User'))