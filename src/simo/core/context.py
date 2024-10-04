import importlib
import simo
import pkg_resources
from simo.core.utils.helpers import get_self_ip
from django.apps import apps
from simo.core.models import Instance
from simo.conf import dynamic_settings
from simo.core.utils.helpers import is_update_available
from simo.core.middleware import get_current_instance


def additional_templates_context(request):
    if not request.user.is_authenticated:
        instances = Instance.objects.none()
    else:
        instances = request.user.instances
    ctx = {
        'hub_ip': get_self_ip(),
        'dynamic_settings': dynamic_settings,
        'current_version': pkg_resources.get_distribution('simo').version,
        'update_available': is_update_available(True),
        'instances': instances,
        'current_instance': get_current_instance()
    }

    if request.path == '/admin/':
        ctx['todos'] = []
        for app_name, app in apps.app_configs.items():
            try:
                todos = importlib.import_module('%s.todos' % app.name)
            except ModuleNotFoundError:
                continue
            for f_name, todo_function in todos.__dict__.items():
                if not callable(todo_function):
                    # not a function
                    continue
                res = todo_function()
                if isinstance(res, list):
                    for item in res:
                        item['app_name'] = app_name
                    ctx['todos'].extend(res)

    return ctx
