import os
from django.http import FileResponse, HttpResponse, Http404
from django.db.models import Q
from dal import autocomplete
from .models import Colonel, ColonelPin, I2CInterface


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
                Q(occupied_by=None) | Q(occupied_by=self.forwarded['self'])
            )
        else:
            qs = qs.filter(occupied_by=None)

        if self.forwarded.get('filters'):
            qs = qs.filter(**self.forwarded.get('filters'))

        return qs


class I2CInterfaceSelectAutocomplete(autocomplete.Select2ListView):

    def get_list(self):
        if not self.request.user.is_staff:
            return []

        try:
            colonel = Colonel.objects.get(
                pk=self.forwarded.get("colonel")
            )
        except:
            return []

        return [
            (i.no, i.get_no_display()) for i in
            I2CInterface.objects.filter(colonel=colonel)
        ]
