import json
from urllib.parse import parse_qs
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.db.models import Q
from django.conf import settings

from simo.users.models import User, InstanceUser, ComponentPermission
from simo.core.models import Component
from simo.users.sso_views import SSO_SERVER, SSO_PRIVATE_KEY
from itsdangerous import URLSafeTimedSerializer
from webservices.sync import SyncConsumer


def _parse_body(request):
    # Support form-encoded, JSON, and query-string bodies
    content_type = request.META.get('CONTENT_TYPE', '')
    data = {}
    try:
        if 'application/json' in content_type:
            data = json.loads(request.body.decode() or '{}')
        elif 'application/x-www-form-urlencoded' in content_type:
            data = {k: v[0] if isinstance(v, list) else v for k, v in parse_qs(request.body.decode()).items()}
        else:
            # Fallback: attempt JSON, else ignore
            try:
                data = json.loads(request.body.decode() or '{}')
            except Exception:
                data = {}
    except Exception:
        data = {}
    # Also allow query params
    for k, v in request.GET.items():
        if k not in data:
            data[k] = v
    return data


def _extract_token(request, data):
    # Prefer Authorization header: "Bearer <token>"
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.lower().startswith('bearer '):
        return auth.split(' ', 1)[1].strip()
    # Fallback to explicit token, or password field
    if 'token' in data:
        return data['token']
    if 'password' in data and data['password']:
        return data['password']
    return ''


def _verify_sso_token(token):
    """
    Verify SSO token with SIMO SSO server and return matching User, or None.
    """
    if not token:
        return None
    consumer = SyncConsumer(SSO_SERVER, '', SSO_PRIVATE_KEY)
    try:
        access_token = URLSafeTimedSerializer(SSO_PRIVATE_KEY).loads(token)
        user_data = consumer.consume('/verify/', {'access_token': access_token})
    except Exception:
        return None
    if not user_data or 'email' not in user_data:
        return None
    # Only allow existing users on this hub
    user = User.objects.filter(email=user_data['email']).first()
    if not user:
        return None
    if not user.is_active:
        return None
    return user


def _get_user_from_request(request, data):
    # Try SSO token first
    token = _extract_token(request, data)
    user = _verify_sso_token(token)
    if user:
        return user
    # Fallback to username (email)
    username = data.get('username') or data.get('user') or ''
    if username:
        return User.objects.filter(email=username).first()
    return None


def _topic_parts(topic):
    parts = (topic or '').split('/')
    # Expected: SIMO/obj-state/<instance-id>/<Model>-<id>
    if len(parts) < 4 or parts[0] != 'SIMO':
        return {}
    return {
        'namespace': parts[1],
        'instance_id': parts[2],
        'object': parts[3],
    }


def _is_user_on_instance(user, instance_id):
    if user.is_master:
        return True
    return InstanceUser.objects.filter(user=user, instance_id=instance_id, is_active=True).exists()


def _can_read_component_topic(user, instance_id, component_id):
    if user.is_master:
        return True
    return ComponentPermission.objects.filter(
        role__in=user.roles.all(),
        component_id=component_id,
        component__zone__instance_id=instance_id,
        read=True,
    ).exists()


@csrf_exempt
def mqtt_auth(request):
    """
    HTTP auth endpoint for the MQTT broker plugin.
    Validates SSO token and allows connection for existing active users.
    """
    data = _parse_body(request)
    # Allow internal 'root' service account via shared secret
    if (data.get('username') == 'root' or data.get('user') == 'root') and data.get('password') == settings.SECRET_KEY:
        return JsonResponse({'ok': True, 'user_id': 0})
    user = _get_user_from_request(request, data)
    if not user:
        return JsonResponse({'ok': False}, status=403)
    return JsonResponse({'ok': True, 'user_id': user.id})


@csrf_exempt
def mqtt_superuser(request):
    data = _parse_body(request)
    if (data.get('username') == 'root' or data.get('user') == 'root') and data.get('password') == settings.SECRET_KEY:
        return JsonResponse({'superuser': True})
    user = _get_user_from_request(request, data)
    if not user:
        return JsonResponse({'superuser': False}, status=403)
    return JsonResponse({'superuser': bool(user.is_master)})


@csrf_exempt
def mqtt_acl(request):
    """
    ACL check endpoint.
    Expected fields: topic, acc (1=read/subscribe, 2=write/publish)
    """
    data = _parse_body(request)
    # Root internal account has full access
    if (data.get('username') == 'root' or data.get('user') == 'root'):
        return JsonResponse({'ok': True})
    user = _get_user_from_request(request, data)
    if not user:
        return JsonResponse({'ok': False}, status=403)

    topic = data.get('topic', '')
    acc = int(data.get('acc', 1))

    # Allow writes only to per-user control topics and only with write permission
    if acc != 1:
        # Expected control topic: SIMO/user/<user-id>/control/<instance-id>/Component-<component-id>
        tparts = (topic or '').split('/')
        if len(tparts) >= 6 and tparts[0] == 'SIMO' and tparts[1] == 'user' and tparts[3] == 'control':
            try:
                path_user_id = int(tparts[2])
                instance_id = int(tparts[4])
            except Exception:
                return JsonResponse({'ok': False}, status=403)
            if user.id != path_user_id:
                return JsonResponse({'ok': False}, status=403)
            obj = tparts[5]
            if obj.startswith('Component-'):
                try:
                    comp_id = int(obj.split('-', 1)[1])
                except Exception:
                    return JsonResponse({'ok': False}, status=403)
                # Require write permission
                if user.is_master:
                    return JsonResponse({'ok': True})
                # User must be active on instance
                if not _is_user_on_instance(user, instance_id):
                    return JsonResponse({'ok': False}, status=403)
                has_write = ComponentPermission.objects.filter(
                    role__in=user.roles.all(),
                    component_id=comp_id,
                    component__zone__instance_id=instance_id,
                    write=True,
                ).exists()
                return JsonResponse({'ok': bool(has_write)}, status=200 if has_write else 403)
        # All other writes denied
        return JsonResponse({'ok': False}, status=403)

    # Read access: only allow per-user feed topics for external clients
    # SIMO/user/<user-id>/feed/<instance-id>/<Object>
    tparts = (topic or '').split('/')
    if len(tparts) >= 6 and tparts[0] == 'SIMO' and tparts[1] == 'user' and tparts[3] == 'feed':
        try:
            path_user_id = int(tparts[2])
            instance_id = int(tparts[4])
        except Exception:
            return JsonResponse({'ok': False}, status=403)
        if user.id != path_user_id:
            return JsonResponse({'ok': False}, status=403)
        allowed = _is_user_on_instance(user, instance_id)
        return JsonResponse({'ok': bool(allowed)}, status=200 if allowed else 403)

    # Allow per-user notifications and control responses
    # SIMO/user/<user-id>/perms-changed
    if len(tparts) == 4 and tparts[0] == 'SIMO' and tparts[1] == 'user' and tparts[3] == 'perms-changed':
        try:
            path_user_id = int(tparts[2])
        except Exception:
            return JsonResponse({'ok': False}, status=403)
        return JsonResponse({'ok': user.id == path_user_id})

    # SIMO/user/<user-id>/control-resp/<request-id>
    if len(tparts) >= 5 and tparts[0] == 'SIMO' and tparts[1] == 'user' and tparts[3] == 'control-resp':
        try:
            path_user_id = int(tparts[2])
        except Exception:
            return JsonResponse({'ok': False}, status=403)
        return JsonResponse({'ok': user.id == path_user_id})

    # Deny access to internal obj-state and other topics for external clients
    return JsonResponse({'ok': False}, status=403)
