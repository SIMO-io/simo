import importlib
import inspect
from django.apps import apps
from ..gateways import BaseGatewayHandler
from ..app_widgets import BaseAppWidget


def get_controller_types_map(gateway=None):
    from ..controllers import ControllerBase
    controllers_map = {}
    for name, app in apps.app_configs.items():
        if name in (
            'auth', 'admin', 'contenttypes', 'sessions', 'messages',
            'staticfiles'
        ):
            continue
        try:
            configs = importlib.import_module('%s.controllers' % app.name)
        except ModuleNotFoundError:
            continue
        for cls_name, cls in configs.__dict__.items():
            if inspect.isclass(cls) and issubclass(cls, ControllerBase) \
                and not inspect.isabstract(cls):
                if gateway:
                    try:
                        same = gateway.type == cls.gateway_class.uid
                    except:
                        continue
                    else:
                        if not same:
                            continue
                controllers_map[cls.uid] = cls
    return controllers_map


def get_controller_types_choices(gateway=None):
    choices = []
    for controller_cls in get_controller_types_map(gateway).values():
        choices.append((controller_cls.uid, controller_cls.name))
    return choices


#ALL_CONTROLLER_TYPES = get_controller_types_map()
# CONTROLLER_TYPE_CHOICES = [
#     (slug, cls.name) for slug, cls in ALL_CONTROLLER_TYPES.items()
# ]
# CONTROLLER_TYPE_CHOICES.sort(key=lambda e: e[0])

def get_all_gateways():
    all_gateways = {}
    for name, app in apps.app_configs.items():
        if name in (
            'auth', 'admin', 'contenttypes', 'sessions', 'messages',
            'staticfiles'
        ):
            continue
        try:
            gateways = importlib.import_module('%s.gateways' % app.name)
        except ModuleNotFoundError:
            continue
        for cls_name, cls in gateways.__dict__.items():
            if inspect.isclass(cls) and issubclass(cls, BaseGatewayHandler) \
            and cls != BaseGatewayHandler and not inspect.isabstract(cls):
                all_gateways[cls.uid] = cls
    return all_gateways


def get_gateway_choices():
    choices = [
        (slug, cls.name) for slug, cls in get_all_gateways().items()
    ]
    choices.sort(key=lambda e: e[1])
    return choices


ALL_BASE_TYPES = {}
for name, app in apps.app_configs.items():
    if name in (
        'auth', 'admin', 'contenttypes', 'sessions', 'messages',
        'staticfiles'
    ):
        continue
    try:
        configs = importlib.import_module('%s.base_types' % app.name)
    except ModuleNotFoundError:
        continue
    ALL_BASE_TYPES.update(configs.__dict__.get('BASE_TYPES', {}))

BASE_TYPE_CHOICES = list(ALL_BASE_TYPES.items())
BASE_TYPE_CHOICES.sort(key=lambda e: e[0])


APP_WIDGETS = {}

for name, app in apps.app_configs.items():
    if name in (
            'auth', 'admin', 'contenttypes', 'sessions', 'messages',
            'staticfiles'
    ):
        continue
    try:
        app_widgets = importlib.import_module('%s.app_widgets' % app.name)
    except ModuleNotFoundError:
        continue
    for cls_name, cls in app_widgets.__dict__.items():
        if inspect.isclass(cls) and issubclass(cls, BaseAppWidget) \
                and cls != BaseAppWidget:
            APP_WIDGETS[cls.uid] = cls


APP_WIDGET_CHOICES = [(slug, cls.name) for slug, cls in APP_WIDGETS.items()]
APP_WIDGET_CHOICES.sort(key=lambda e: e[1])


