import pytz
from django.utils import timezone
from django.shortcuts import render


class InstanceCarrier:
    instance = None

_instance_carrier = InstanceCarrier()


def introduce_instance(instance, request=None):
    if request and request.user.is_authenticated \
    and instance not in request.user.instances:
        return
    _instance_carrier.instance = instance
    if request:
        request.session['instance_id'] = instance.id
        request.instance = instance


def drop_current_instance(request=None):
    if request and 'instance_id' in request.session:
        request.session.pop('instance_id')
    _instance_carrier.instance = None


def get_current_instance(request=None):
    from simo.core.models import Instance
    if request and request.session.get('instance_id'):
        instance = Instance.objects.filter(
            id=request.session['instance_id'], is_active=True
        ).first()
        if not instance:
            del request.session['instance_id']
        else:
            introduce_instance(instance, request)

    instance = getattr(_instance_carrier, 'instance', None)

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

        if request.path.startswith('/admin'):
            if request.user.is_authenticated and not request.user.is_master:
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
            try:
                # should never, but just in case
                tz = pytz.timezone(instance.timezone)
                timezone.activate(tz)
            except:
                tz = pytz.timezone('UTC')
                timezone.activate(tz)

        response = get_response(request)

        return response

    return middleware
