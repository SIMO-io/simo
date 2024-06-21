from django.apps import AppConfig



class SIMOCoreAppConfig(AppConfig):
    name = 'simo.core'

    def ready(self):
        from actstream import registry
        registry.register(self.get_model('Component'))
        registry.register(self.get_model('Gateway'))
        registry.register(self.get_model('Instance'))
        registry.register(self.get_model('Zone'))
        registry.register(self.get_model('Category'))


