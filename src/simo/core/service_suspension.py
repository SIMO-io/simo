from django.utils.translation import gettext_lazy as _

from simo.conf import dynamic_settings


CONTROL_BLOCKED_ERROR = _(
    "Direct Colonel control is disabled on this hub while service suspension is active."
)
AUTOMATION_BLOCKED_ERROR = _(
    "Automation scripts are disabled on this hub while service suspension is active."
)


def is_service_suspended():
    try:
        return bool(dynamic_settings['core__service_suspended'])
    except Exception:
        return False


def is_colonel_component(component):
    if not component:
        return False
    try:
        if component.gateway.type != 'simo.fleet.gateways.FleetGatewayHandler':
            return False
        return bool((component.config or {}).get('colonel'))
    except Exception:
        return False


def is_direct_colonel_control_blocked(user, component):
    if not is_service_suspended():
        return False
    if not is_colonel_component(component):
        return False
    return not bool(getattr(user, 'is_master', False))


def is_script_start_blocked(component, method_name):
    if not is_service_suspended():
        return False
    if getattr(component, 'base_type', None) != 'script':
        return False
    if method_name in ('start', 'play'):
        return True
    if method_name == 'toggle':
        return component.value != 'running'
    return False


def _sync_colonels_config():
    from simo.fleet.models import Colonel

    for colonel in Colonel.objects.all():
        try:
            colonel.update_config()
        except Exception:
            pass


def _stop_running_scripts():
    from simo.core.models import Component

    for component in Component.objects.filter(base_type='script', value='running'):
        meta = dict(component.meta or {})
        if not meta.get('service_suspension_resume'):
            meta['service_suspension_resume'] = True
            component.meta = meta
            component.save(update_fields=['meta'])
        try:
            component.controller.stop()
        except Exception:
            pass


def _resume_suspended_scripts():
    from simo.core.models import Component

    for component in Component.objects.filter(base_type='script'):
        meta = dict(component.meta or {})
        if not meta.pop('service_suspension_resume', False):
            continue
        component.meta = meta
        component.save(update_fields=['meta'])
        if component.value == 'stopped':
            try:
                component.controller.start()
            except Exception:
                pass


def sync_service_suspension(suspended):
    _sync_colonels_config()
    if suspended:
        _stop_running_scripts()
    else:
        _resume_suspended_scripts()
