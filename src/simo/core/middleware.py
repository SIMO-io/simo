import pytz
import threading
from django.urls import set_script_prefix
from django.utils import timezone
from simo.conf import dynamic_settings

_thread_locals = threading.local()


def get_current_request():
    try:
        return _thread_locals.request
    except:
        pass


def simo_router_middleware(get_response):

    def middleware(request):
        _thread_locals.request = request

        request.relay = None

        if request.META.get('HTTP_HOST', '').endswith('.simo.io'):
            router_prefix = dynamic_settings['core__remote_http']
            router_prefix = router_prefix[router_prefix.find('simo.io') + 7:]
            set_script_prefix(router_prefix)
            request.path = router_prefix + request.path

        response = get_response(request)

        return response

    return middleware


def instance_middleware(get_response):

    def middleware(request):
        from simo.core.models import Instance

        instance = None
        if request.resolver_match:
            instance = Instance.objects.filter(
                slug=request.resolver_match.kwargs.get('instance_slug')
            ).first()

        if not instance:
            if request.user.is_authenticated:
                if len(request.user.instances) == 1:
                    for inst in request.user.instances:
                        instance = inst

        if instance:
            tz = pytz.timezone(instance.timezone)
            timezone.activate(tz)

        response = get_response(request)

        return response

    return middleware
