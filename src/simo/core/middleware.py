import pytz
from django.utils import timezone
from django.shortcuts import render
from contextvars import ContextVar


_current_instance: ContextVar = ContextVar('simo_current_instance', default=None)


def introduce_instance(instance, request=None):
    """Set current instance for the current request/task context.

    Returns a token that can be used with ``reset_instance``.
    """
    if request and request.user.is_authenticated \
    and instance not in request.user.instances:
        # Avoid leaving a poisoned instance_id in the session.
        try:
            if request.session.get('instance_id') == getattr(instance, 'id', None):
                request.session.pop('instance_id')
        except Exception:
            pass
        return
    token = _current_instance.set(instance)
    if request and instance is not None and request.user.is_authenticated:
        request.session['instance_id'] = instance.id
        request.instance = instance
    return token


def reset_instance(token):
    _current_instance.reset(token)


def drop_current_instance(request=None):
    if request and 'instance_id' in request.session:
        request.session.pop('instance_id')
    _current_instance.set(None)


def get_current_instance(request=None):
    from simo.core.models import Instance
    if request and request.session.get('instance_id'):
        instance = Instance.objects.filter(
            id=request.session['instance_id'], is_active=True
        ).first()
        if not instance:
            del request.session['instance_id']
        else:
            token = introduce_instance(instance, request)
            if token is None:
                # Session pointed at an instance the user cannot access.
                try:
                    del request.session['instance_id']
                except Exception:
                    pass

    instance = _current_instance.get()

    # NEVER FORCE THIS! IT's A very BAD IDEA!
    # For example gateways run on an instance neutral environment!
    # if not instance:
    #     from .models import Instance
    #     instance = Instance.objects.filter(is_active=True).first()
    #     if instance:
    #         introduce_instance(instance)
    return instance


def simo_router_middleware(get_response):

    def middleware(request):

        request.relay = None

        response = get_response(request)

        return response

    return middleware


def instance_middleware(get_response):

    def middleware(request):

        # Clear any leaked instance context (Celery, threads, prior requests).
        token = _current_instance.set(None)

        if request.path.startswith('/admin'):
            if request.user.is_authenticated and not request.user.is_master:
                try:
                    return render(request, 'admin/msg_page.html', {
                        'page_title': "You are not allowed in here",
                        'msg': "Page you are trying to access is only for hub masters.",
                        'suggestion': "Try switching your user to the one who has proper "
                                      "rights to come here or ask for somebody who already has "
                                      "master rights enable these rights for you."
                    })
                finally:
                    _current_instance.reset(token)

        from simo.core.models import Instance

        instance = None
        # Allow selecting instance via admin query parameter for deep-links
        if request.path.startswith('/admin') and request.GET.get('instance_uid'):
            i = Instance.objects.filter(
                uid=request.GET.get('instance_uid'), is_active=True
            ).first()
            if i:
                instance = i
                introduce_instance(instance, request)
        # API calls
        if request.resolver_match:
            instance = Instance.objects.filter(
                slug=request.resolver_match.kwargs.get('instance_slug'),
                is_active=True
            ).first()

        if not instance:
            instance = get_current_instance(request)

        if not instance:
            if request.user.is_authenticated:
                if request.user.instances:
                    instance = list(request.user.instances)[0]

        if instance:
            introduce_instance(instance, request)
            try:
                # should never, but just in case
                tz = pytz.timezone(instance.timezone)
                timezone.activate(tz)
            except:
                tz = pytz.timezone('UTC')
                timezone.activate(tz)

        try:
            response = get_response(request)
            return response
        finally:
            try:
                timezone.deactivate()
            except Exception:
                pass
            _current_instance.reset(token)

    return middleware
