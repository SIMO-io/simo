import importlib
import inspect
from django.apps import apps
from ..gateways import BaseGatewayHandler
from ..app_widgets import BaseAppWidget
from ..base_types import BaseComponentType


# ----- Base type discovery (must be defined before controller discovery) -----
def get_base_type_class_map():
    """Discover BaseComponentType subclasses across installed apps.

    Returns a dict mapping slug -> type class.
    """
    base_types = {}
    for name, app in apps.app_configs.items():
        if name in (
            'auth', 'admin', 'contenttypes', 'sessions', 'messages',
            'staticfiles'
        ):
            continue
        try:
            module = importlib.import_module(f'{app.name}.base_types')
        except ModuleNotFoundError:
            continue
        for cls_name, cls in module.__dict__.items():
            if not inspect.isclass(cls):
                continue
            if not issubclass(cls, BaseComponentType) or cls is BaseComponentType:
                continue
            if not getattr(cls, 'slug', None):
                continue
            if cls.slug in base_types:
                raise RuntimeError(
                    f"Duplicate base type slug '{cls.slug}' defined by "
                    f"{base_types[cls.slug].__module__}.{base_types[cls.slug].__name__} "
                    f"and {cls.__module__}.{cls.__name__}"
                )
            base_types[cls.slug] = cls
    return base_types


BASE_TYPE_CLASS_MAP = get_base_type_class_map()


def get_all_base_types():
    """Build a combined map of slug -> name from classes and legacy dicts."""
    all_types = {slug: cls.name for slug, cls in BASE_TYPE_CLASS_MAP.items()}
    # Backward-compatible: merge any legacy dict entries not covered by classes
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
        for slug, display in configs.__dict__.get('BASE_TYPES', {}).items():
            if slug not in all_types:
                all_types[slug] = display
    return all_types


ALL_BASE_TYPES = get_all_base_types()
BASE_TYPE_CHOICES = sorted(list(ALL_BASE_TYPES.items()), key=lambda e: e[0])


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

            # Validate controller against its base type contract if available.
            # Support either `base_type_cls` or legacy `base_type` (slug or class).
            declared = getattr(cls, 'base_type_cls', None)
            slug = None
            if declared and inspect.isclass(declared) and issubclass(declared, BaseComponentType):
                slug = declared.slug
            else:
                bt = getattr(cls, 'base_type', None)
                if isinstance(bt, str):
                    slug = bt
                elif inspect.isclass(bt) and issubclass(bt, BaseComponentType):
                    slug = bt.slug
            bt_cls = BASE_TYPE_CLASS_MAP.get(slug) if slug else None
            if bt_cls:
                bt_cls.validate_controller(cls)

            controllers_map[cls.uid] = cls
    return controllers_map


CONTROLLER_TYPES_MAP = get_controller_types_map()


def get_controller_types_choices(gateway=None):
    choices = []
    for controller_cls in get_controller_types_map(gateway).values():
        choices.append((controller_cls.uid, f"{controller_cls.gateway_class.name} | {controller_cls.name}"))
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
