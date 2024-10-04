import pytz
import threading
import re
from django.utils import timezone
from django.shortcuts import render


_thread_locals = threading.local()


def get_current_request():
    try:
        return _thread_locals.request
    except:
        pass


def introduce_instance(instance, request=None):
    if request and request.user.is_authenticated \
    and instance not in request.user.instances:
        return
    _thread_locals.instance = instance
    if request:
        request.session['instance_id'] = instance.id
        request.instance = instance


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

        if request.path.startswith('/admin'):
            if not (request.user.is_authenticated and request.user.is_master):
                return render(request, 'admin/msg_page.html', {
                    'page_title': "You are not allowed in here",
                    'msg': "Page you are trying to access is only for hub masters.",
                    'suggestion': "Try switching your user to the one who has proper "
                                  "rights to come here or ask for somebody who already has "
                                  "master rights enable these rights for you."
                })

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
