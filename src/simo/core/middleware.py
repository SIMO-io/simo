import pytz
import threading
import re
from django.utils import timezone


_thread_locals = threading.local()


def get_current_request():
    try:
        return _thread_locals.request
    except:
        pass


def introduce_instance(instance, request=None):
    _thread_locals.instance = instance
    if request:
        request.session['instance_id'] = instance.id


def get_current_instance(request=None):
    instance = getattr(_thread_locals, 'instance', None)
    if not instance and request and request.session.get('instance_id'):
        from simo.core.models import Instance
        instance = Instance.objects.filter(
            id=request.session['instance_id']
        ).first()
        if not instance:
            del request.session['instance_id']
        else:
            introduce_instance(instance, request)
    return instance


def simo_router_middleware(get_response):

    def middleware(request):
        _thread_locals.request = request

        request.relay = None

        response = get_response(request)

        return response

    return middleware


def instance_middleware(get_response):

    def middleware(request):
        from simo.core.models import Instance

        instance = None
        # API calls
        if request.resolver_match:
            instance = Instance.objects.filter(
                slug=request.resolver_match.kwargs.get('instance_slug')
            ).first()

        if not instance:
            instance = get_current_instance(request)

        if not instance:
            if request.user.is_authenticated:
                if request.user.instances:
                    instance = list(request.user.instances)[0]

        if instance:
            introduce_instance(instance, request)
            tz = pytz.timezone(instance.timezone)
            timezone.activate(tz)

        response = get_response(request)

        return response

    return middleware
