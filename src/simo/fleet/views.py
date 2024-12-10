from django.http import HttpResponse, Http404
from django.db.models import Q
from dal import autocomplete
from simo.core.utils.helpers import search_queryset
from simo.core.models import Component
from simo.core.middleware import get_current_instance
from .models import Colonel, ColonelPin, Interface


def colonels_ping(request):
    return HttpResponse('pong')


class ColonelsAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            raise Http404()

        instance = get_current_instance(self.request)
        if not instance:
            return Colonel.objects.none()

        qs = Colonel.objects.filter(instance=instance)

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

