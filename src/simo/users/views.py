import re
from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from dal import autocomplete
from django.contrib.auth import logout
from django.urls import re_path
from django.shortcuts import get_object_or_404, render
from django.db.transaction import atomic
from django.utils import timezone
from django.urls import reverse_lazy
from django.utils.http import urlencode
from django.template.loader import render_to_string
from django.conf import settings
from django.http import (
    JsonResponse, HttpResponseRedirect, HttpResponse, Http404
)
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from simo.core.api_auth import SecretKeyAuth, IsAuthenticated as SessionAuth
from simo.core.middleware import get_current_instance
from simo.users.permissions import IsActivePermission
from simo.core.utils.helpers import search_queryset
from .models import InstanceInvitation, PermissionsRole, InstanceUser
from .models import User


@atomic
def accept_invitation(request, token):

    invitation = get_object_or_404(InstanceInvitation, token=token)

    if invitation.expire_date < timezone.now():
        status = 'error'
        title = "Invitation expired"
        msg = render_to_string(
            'invitations/expired_msg.html', {
                'invitation': invitation,
            }
        )
        suggestion = render_to_string(
            'invitations/expired_suggestion.html', {
                'invitation': invitation,
            }
        )

    elif invitation.taken_by:
        status = 'error'
        title = "Invitation is already taken"
        msg = render_to_string(
            'invitations/taken_msg.html', {
                'invitation': invitation, 'user': request.user,
            }
        )
        suggestion = render_to_string(
            'invitations/taken_suggestion.html', {
                'invitation': invitation, 'user': request.user,
            }
        )

    else:
        if request.user.is_authenticated:
            logout(request)

        # elif request.user.is_authenticated:
        #     status = 'error'
        #     title = "You are already authenticated"
        #     msg = render_to_string(
        #         'invitations/authenticated_msg.html', {
        #             'invitation': invitation, 'user': request.user,
        #         }
        #     )
        #     suggestion = render_to_string(
        #         'invitations/authenticated_suggestion.html', {
        #             'invitation': invitation,
        #             'user': request.user,
        #         }
        #     )

        #else:

        url = '%s?%s' % (
            reverse_lazy('login'),
            urlencode([('invitation', invitation.token)])
        )
        if request.headers.get('User-Agent', '').startswith("SIMO"):
            return JsonResponse({'status': 'need-login', 'redirect': url})
        return HttpResponseRedirect(url)

    if request.headers.get('User-Agent', '').startswith("SIMO"):
        return JsonResponse({
            'status': status, 'title': title, 'msg': msg,
            'suggestion': suggestion
        })
    else:
        return render(request, 'admin/msg_page.html', {
            'status': 'danger' if status == 'error' else status, 'page_title': title,
            'msg': msg, 'suggestion': suggestion
        })

def serve_protected(request, path, prefix=''):
    # Basic path traversal hardening
    if not path or '..' in path or path.startswith('/'):
        raise Http404()

    user = request.user if request.user.is_authenticated else None
    if not user:
        secret = request.META.get('HTTP_SECRET')
        if secret:
            user = User.objects.filter(secret_key=secret).first()

    if not user or not user.is_active:
        # Don't even let anyone know if anything exists in here
        raise Http404()

    # Throttle protected static/media access.
    if prefix.startswith('/media'):
        scope = 'media'
        parts = [p for p in path.split('/') if p]
        if parts:
            if parts[0] == 'icons':
                scope = 'media.icons'
            elif parts[0] == 'avatars':
                scope = 'media.avatars'
            elif parts[0] == 'instances':
                scope = 'media.instances'
        from simo.core.throttling import check_throttle
        wait = check_throttle(request=request, scope=scope)
        if wait > 0:
            raise Http404()

    # Tenant-safe media access
    if prefix.startswith('/media'):
        parts = [p for p in path.split('/') if p]
        if not parts:
            raise Http404()

        # Instance-owned media: /media/instances/<instance_uid>/...
        if len(parts) >= 3 and parts[0] == 'instances':
            instance_uid = parts[1]
            instance_id = None
            try:
                from simo.core.models import Instance
                instance_id = Instance.objects.filter(uid=instance_uid, is_active=True).values_list('id', flat=True).first()
            except Exception:
                instance_id = None
            if not instance_id:
                raise Http404()
            if not user.is_master:
                if not InstanceUser.objects.filter(
                    user=user, instance_id=instance_id, is_active=True
                ).exists():
                    raise Http404()

        # User-owned avatars: /media/avatars/<media_uid>/...
        elif len(parts) >= 3 and parts[0] == 'avatars':
            media_uid = parts[1]
            target_user = User.objects.filter(media_uid=media_uid).values('id').first()
            if not target_user:
                raise Http404()
            target_user_id = target_user['id']
            if not (user.is_master or user.id == target_user_id):
                # Allow only if users share at least one active instance
                my_instance_ids = InstanceUser.objects.filter(
                    user=user, is_active=True
                ).values('instance_id')
                if not InstanceUser.objects.filter(
                    user_id=target_user_id, is_active=True,
                    instance_id__in=my_instance_ids,
                ).exists():
                    raise Http404()

        # Global media (not instance-bound): icons
        elif parts[0] == 'icons':
            pass

        # Anything else is treated as legacy/unscoped and denied
        else:
            raise Http404()

    # Static is safe for any authenticated user.
    response = HttpResponse(status=200)
    response['Content-Type'] = ''
    response['X-Accel-Redirect'] = '/protected' + prefix + path
    return response


def protected_static(prefix, **kwargs):
    return re_path(
        r'^%s(?P<path>.*)$' % re.escape(prefix.lstrip('/')),
        serve_protected, kwargs={'prefix': prefix}
    )


class RolesAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            raise Http404()

        qs = PermissionsRole.objects.filter(instance=get_current_instance(self.request))

        if self.request.GET.get('value'):
            qs = qs.filter(pk__in=self.request.GET['value'].split(','))
        elif self.q:
            qs = search_queryset(qs, self.q, ('name',))

        return qs.distinct()


@login_required
def mqtt_credentials(request):
    """Return MQTT credentials for the authenticated user.
    Response payload:
      - username: user's email
      - password: user's MQTT secret
    """
    return JsonResponse({
        'username': request.user.email,
        'password': request.user.secret_key,
        'user_id': request.user.id
    })


@api_view(["GET"])
@authentication_classes([SecretKeyAuth, SessionAuth])
@permission_classes([IsAuthenticated, IsActivePermission])
def whoami(request):
    """Bootstrap endpoint for simo-sdk.

    Query params:
      - instance: instance slug or uid to select.
    """

    user = request.user
    requested = (request.GET.get('instance') or '').strip()
    instances_qs = user.instances

    instances_payload = [
        {
            'uid': inst.uid,
            'slug': inst.slug,
            'name': inst.name,
            'timezone': inst.timezone,
            'units_of_measure': inst.units_of_measure,
        }
        for inst in instances_qs
    ]

    selected_instance = None
    if requested:
        selected_instance = instances_qs.filter(slug=requested).first()
        if not selected_instance:
            selected_instance = instances_qs.filter(uid=requested).first()
        if not selected_instance:
            raise Http404()
    elif len(instances_payload) == 1:
        selected_instance = instances_qs.first()

    parsed = urlparse(request.build_absolute_uri('/'))
    mqtt_host = parsed.hostname
    mqtt_tls = (parsed.scheme or '').lower() == 'https'
    mqtt_port = 443 if mqtt_tls else 80

    resp: dict = {
        'user': {
            'id': user.id,
            'email': user.email,
            'name': user.name,
            'is_master': bool(getattr(user, 'is_master', False)),
        },
        'instances': instances_payload,
        'mqtt': {
            'host': mqtt_host,
            'port': mqtt_port,
            'tls': mqtt_tls,
            'transport': 'websockets',
            'path': '/mqtt/',
        },
    }

    if selected_instance:
        resp['selected_instance'] = {
            'uid': selected_instance.uid,
            'slug': selected_instance.slug,
            'name': selected_instance.name,
            'timezone': selected_instance.timezone,
            'units_of_measure': selected_instance.units_of_measure,
        }

    return Response(resp)
