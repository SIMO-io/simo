from django.http import HttpResponse, Http404
from django.db.models import Q
from dal import autocomplete
from simo.core.utils.helpers import search_queryset
from simo.core.models import Component
from .models import Colonel, ColonelPin, Interface


def colonels_ping(request):
    return HttpResponse('pong')


class PinsSelectAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        if not self.request.user.is_staff:
            return ColonelPin.objects.none()

        try:
            colonel = Colonel.objects.get(
                pk=self.forwarded.get("colonel")
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

        if self.q:
            qs = search_queryset(qs, self.q, ('label', ))

        return qs


class InterfaceSelectAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        if not self.request.user.is_staff:
            return Interface.objects.none()

        try:
            colonel = Colonel.objects.get(
                pk=self.forwarded.get("colonel")
            )
        except:
            return Interface.objects.none()

        qs = Interface.objects.filter(colonel=colonel)

        if self.forwarded.get('filters'):
            qs = qs.filter(**self.forwarded.get('filters'))

        return qs


class ControlInputSelectAutocomplete(autocomplete.Select2ListView):

    def get_list(self):

        try:
            colonel = Colonel.objects.get(
                pk=self.forwarded.get("colonel")
            )
            pins_qs = ColonelPin.objects.filter(colonel=colonel)
        except:
            pins_qs = ColonelPin.objects.all()

        if self.forwarded.get('self') and self.forwarded['self'].startswith('pin-'):
            pins_qs = pins_qs.filter(
                Q(occupied_by_id=None) | Q(id=int(self.forwarded['self'][4:]))
            )
        else:
            pins_qs = pins_qs.filter(occupied_by_id=None)

        if self.forwarded.get('pin_filters'):
            pins_qs = pins_qs.filter(**self.forwarded.get('pin_filters'))

        if self.q:
            pins_qs = search_queryset(pins_qs, self.q, ('label',))

        buttons_qs = Component.objects.filter(
            base_type='button'
        ).select_related('zone')

        if self.forwarded.get('button_filters'):
            buttons_qs = buttons_qs.filter(**self.forwarded.get('button_filters'))

        if self.q:
            buttons_qs = search_queryset(
                buttons_qs, self.q, ('name', 'zone__name', 'category__name')
            )

        return [(f'pin-{pin.id}', str(pin)) for pin in pins_qs] + \
               [(f'button-{button.id}',
                 f"{button.zone.name} | {button.name}"
                 if button.zone else button.name)
                for button in buttons_qs]