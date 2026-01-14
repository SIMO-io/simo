import json
import time
import uuid

from django.db import DatabaseError, IntegrityError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.cache import cache
from dal import autocomplete
from simo.core.utils.helpers import search_queryset
from simo.core.models import Instance, Zone, Component
from simo.core.middleware import get_current_instance, introduce_instance
from simo.core.utils.decorators import simo_csrf_exempt
from .models import Colonel, ColonelPin, Interface, SentinelPairingRequest
from .forms import SentinelDeviceConfigForm


def colonels_ping(request):
    return HttpResponse('pong')


def _json_error(status, message, http_status=400, extra=None):
    payload = {'status': status, 'message': message}
    if isinstance(extra, dict) and extra:
        payload.update(extra)
    return JsonResponse(payload, status=http_status)


def _start_sentinel_pairing_request(*, user, instance, colonel_uid):
    token = uuid.uuid4()
    now = timezone.now()

    # Ensure a single row per user; update token for newest request.
    for _ in range(3):
        try:
            with transaction.atomic():
                req = SentinelPairingRequest.objects.select_for_update().filter(
                    user=user
                ).first()
                if not req:
                    req = SentinelPairingRequest(user=user)
                req.instance = instance
                req.colonel_uid = colonel_uid
                req.status = 'pending'
                req.active_token = token
                req.started_at = now
                req.finished_at = None
                req.last_error = ''
                req.save()
            return token
        except IntegrityError:
            # Concurrent first-time requests can race creating the row.
            continue

    raise RuntimeError('Unable to create/update SentinelPairingRequest')


def _is_latest_request(*, user, token):
    row = SentinelPairingRequest.objects.filter(user=user).values(
        'active_token', 'status'
    ).first()
    if not row:
        return False
    return row['status'] == 'pending' and row['active_token'] == token


def _finish_pairing_request(*, user, token, status, error_message=''):
    SentinelPairingRequest.objects.filter(
        user=user, active_token=token
    ).update(
        status=status,
        finished_at=timezone.now(),
        last_error=error_message or '',
    )


@require_POST
@simo_csrf_exempt
def new_sentinel(request):

    if not request.user.is_authenticated:
        return _json_error('unauthorized', 'Authentication required.', http_status=403)

    lock_key = f'sentinel-pairing:{request.user.id}'
    if not cache.add(lock_key, '1', timeout=65):
        return _json_error(
            'rate-limit',
            'Another Sentinel pairing request is already running.',
            http_status=429,
        )

    try:
        try:
            data = json.loads(request.body or b'{}')
        except json.JSONDecodeError:
            return _json_error('invalid-json', 'Invalid JSON body.')

        if not isinstance(data, dict):
            return _json_error('invalid-json', 'JSON body must be an object.')

        instance_ident = data.get('instance')
        if instance_ident is None:
            return _json_error('invalid', 'Missing instance.')

        instance = None
        if isinstance(instance_ident, int):
            instance = Instance.objects.filter(id=instance_ident, is_active=True).first()
        elif isinstance(instance_ident, str):
            instance = Instance.objects.filter(
                Q(uid=instance_ident) | Q(slug=instance_ident),
                is_active=True,
            ).first()
            if not instance and instance_ident.isdigit():
                instance = Instance.objects.filter(id=int(instance_ident), is_active=True).first()

        if not instance:
            return _json_error('not-found', 'Instance not found.', http_status=404)

        if not request.user.is_master:
            user_role = request.user.get_role(instance)
            if not user_role or not user_role.is_admin:
                raise Http404()

        zone_value = data.get('zone')
        zone = None
        if isinstance(zone_value, str):
            zone_name = zone_value.strip()
            if not zone_name:
                return _json_error('invalid', 'Zone name is empty.')
            max_len = Zone._meta.get_field('name').max_length
            if len(zone_name) > max_len:
                return _json_error('invalid', f'Zone name too long (max {max_len}).')
            zone, _ = Zone.objects.get_or_create(instance=instance, name=zone_name)
        else:
            try:
                zone_id = int(zone_value)
            except (TypeError, ValueError):
                return _json_error('invalid', 'Zone must be an id or a name.')
            zone = Zone.objects.filter(pk=zone_id, instance=instance).first()
            if not zone:
                return _json_error('not-found', 'Zone not found.', http_status=404)

        colonel_uid = data.get('uid')
        if not colonel_uid:
            return _json_error('invalid', 'Missing colonel uid.')

        try:
            token = _start_sentinel_pairing_request(
                user=request.user,
                instance=instance,
                colonel_uid=colonel_uid,
            )
        except DatabaseError:
            return _json_error(
                'unavailable',
                'Database temporarily unavailable.',
                http_status=503,
            )

        colonel = None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if not _is_latest_request(user=request.user, token=token):
                    _finish_pairing_request(user=request.user, token=token, status='superseded')
                    return _json_error(
                        'superseded',
                        'This request was replaced by a newer one.',
                        http_status=409,
                    )
                colonel = Colonel.objects.filter(
                    uid=colonel_uid, instance=instance, type='sentinel'
                ).first()
            except DatabaseError:
                colonel = None

            if colonel:
                break
            time.sleep(1)

        if not colonel:
            _finish_pairing_request(user=request.user, token=token, status='timeout')
            return _json_error(
                'timeout',
                'Sentinel not discovered within timeout window.',
                http_status=408,
            )

        if not _is_latest_request(user=request.user, token=token):
            return _json_error(
                'superseded',
                'This request was replaced by a newer one.',
                http_status=409,
            )

        # Ensure `get_current_instance()` used in config forms is correct.
        introduce_instance(instance)
        introduce_instance(instance, request)

        try:
            form = SentinelDeviceConfigForm(data={
                'name': data.get('name') or 'Sentinel',
                'zone': zone.id,
                'colonel': colonel.id,
                'assistant': data.get('assistant'),
                'voice': data.get('voice'),
                'language': data.get('language'),
            })
            if not form.is_valid():
                _finish_pairing_request(user=request.user, token=token, status='error')
                return _json_error(
                    'invalid',
                    'Invalid configuration payload.',
                    http_status=400,
                    extra={'errors': form.errors},
                )

            form.save()

            component_ids = list(
                Component.objects.filter(config__colonel=colonel.id).values_list('id', flat=True)
            )
            _finish_pairing_request(user=request.user, token=token, status='completed')
            return JsonResponse(component_ids, safe=False)
        except Exception as e:
            _finish_pairing_request(user=request.user, token=token, status='error', error_message=str(e))
            return _json_error('error', 'Failed to configure sentinel.', http_status=500)
    finally:
        cache.delete(lock_key)





class ColonelsAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            raise Http404()

        instance = get_current_instance(self.request)
        if not instance:
            return Colonel.objects.none()

        qs = Colonel.objects.filter(instance=instance)

        forwarded_filters = getattr(self, 'forwarded', {}).get('filters')
        if isinstance(forwarded_filters, dict) and forwarded_filters:
            qs = qs.filter(**forwarded_filters)

        if self.request.GET.get('value'):
            qs = qs.filter(pk__in=self.request.GET['value'].split(','))
        elif self.q:
            qs = search_queryset(qs, self.q, ('name', ))
        return qs


class PinsSelectAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):

        if not self.request.user.is_authenticated:
            raise Http404()

        instance = get_current_instance(self.request)
        if not instance:
            return ColonelPin.objects.none()

        if self.request.GET.get('value'):
            return ColonelPin.objects.filter(
                pk__in=self.request.GET['value'].split(','),
                colonel__instance=instance
            )

        try:
            colonel = Colonel.objects.get(
                pk=self.forwarded.get("colonel"), instance=instance
            )
        except:
            return ColonelPin.objects.none()

        qs = ColonelPin.objects.filter(colonel=colonel)

        if self.forwarded.get('self'):
            qs = qs.filter(
                Q(occupied_by_id=None) | Q(
                    id=int(self.forwarded['self'])
                )
            )
        else:
            qs = qs.filter(occupied_by_id=None)

        if self.forwarded.get('filters'):
            qs = qs.filter(**self.forwarded.get('filters'))

        qs = search_queryset(qs, self.q, ('label', ))

        return qs


class InterfaceSelectAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            raise Http404()

        try:
            colonel = Colonel.objects.get(
                pk=self.forwarded.get("colonel"),
                instance=get_current_instance(self.request)
            )
        except:
            return Interface.objects.none()

        qs = Interface.objects.filter(colonel=colonel)

        if self.request.GET.get('value'):
            qs = qs.filter(pk__in=self.request.GET['value'].split(','))
        elif self.forwarded.get('filters'):
            qs = qs.filter(**self.forwarded.get('filters'))

        return qs


class ControlInputSelectAutocomplete(autocomplete.Select2ListView):

    def get_list(self):
        if not self.request.user.is_authenticated:
            raise Http404()

        try:
            colonel = Colonel.objects.get(
                pk=self.forwarded.get("colonel"),
                instance=get_current_instance(self.request)
            )
            pins_qs = ColonelPin.objects.filter(colonel=colonel)
        except:
            pins_qs = ColonelPin.objects.filter(
                colonel__instance=get_current_instance(self.request)
            )

        if self.forwarded.get('self') and self.forwarded['self'].startswith('pin-'):
            pins_qs = pins_qs.filter(
                Q(occupied_by_id=None) | Q(id=int(self.forwarded['self'][4:]))
            )
        elif 'value' not in self.request.GET:
            pins_qs = pins_qs.filter(occupied_by_id=None)

        if self.forwarded.get('pin_filters'):
            pins_qs = pins_qs.filter(**self.forwarded.get('pin_filters'))

        buttons_qs = Component.objects.filter(
            base_type='button', zone__instance=get_current_instance(self.request)
        ).select_related('zone')

        if self.forwarded.get('button_filters'):
            buttons_qs = buttons_qs.filter(**self.forwarded.get('button_filters'))

        if self.request.GET.get('value'):
            pin_ids = []
            button_ids = []
            for v in self.request.GET['value'].split(','):
                try:
                    t, id = v.split('-')
                    id = int(id)
                except:
                    continue
                if t == 'pin':
                    pin_ids.append(id)
                elif t == 'button':
                    button_ids.append(id)
            buttons_qs = buttons_qs.filter(id__in=button_ids)
            pins_qs = pins_qs.filter(id__in=pin_ids)

        elif self.q:
            buttons_qs = search_queryset(
                buttons_qs, self.q, ('name', 'zone__name', 'category__name')
            )
            pins_qs = search_queryset(pins_qs, self.q, ('label',))


        return [(f'pin-{pin.id}', str(pin)) for pin in pins_qs] + \
               [(f'button-{button.id}',
                 f"{button.zone.name} | {button.name}"
                 if button.zone else button.name)
                for button in buttons_qs]
