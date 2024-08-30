import importlib
import inspect
from django.apps import apps
from ..gateways import BaseGatewayHandler
from ..app_widgets import BaseAppWidget


def get_controller_types_map(gateway=None, user=None):
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
            if not inspect.isclass(cls):
                continue
            if not issubclass(cls, ControllerBase):
                continue
            if inspect.isabstract(cls):
                continue
            if gateway:
                if issubclass(gateway, BaseGatewayHandler) \
                or isinstance(gateway, BaseGatewayHandler):
                    if gateway.uid != cls.gateway_class.uid:
                        continue
                else:
                    try:
                        same = gateway.handler.uid == cls.gateway_class.uid
                    except:
                        continue
                    else:
                        if not same:
                            continue
            if user and not user.is_master and cls.masters_only:
                continue

            controllers_map[cls.uid] = cls
    return controllers_map


CONTROLLER_TYPES_MAP = get_controller_types_map()


def get_controller_types_choices(gateway=None):
    choices = []
    for controller_cls in get_controller_types_map(gateway).values():
        choices.append((controller_cls.uid, controller_cls.name))
    return choices


CONTROLLER_TYPES_CHOICES = get_controller_types_choices()


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


GATEWAYS_MAP = get_all_gateways()


def get_gateway_choices():
    choices = [
        (slug, cls.name) for slug, cls in GATEWAYS_MAP.items()
    ]
    choices.sort(key=lambda e: e[1])
    return choices

GATEWAYS_CHOICES = get_gateway_choices()


CONTROLLERS_BY_GATEWAY = {}
for gateway_slug, gateway_cls in GATEWAYS_MAP.items():
    CONTROLLERS_BY_GATEWAY[gateway_slug] = {}
    for ctrl_uid, ctrl_cls in get_controller_types_map(gateway_cls).items():
        CONTROLLERS_BY_GATEWAY[gateway_slug][ctrl_uid] = ctrl_cls


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


