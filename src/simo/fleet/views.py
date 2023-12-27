import os
from django.http import FileResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404
from dal import autocomplete
from .models import Colonel, I2CInterface
from .utils import get_gpio_pins_choices


def colonels_ping(request):
    return HttpResponse('pong')


class PinsSelectAutocomplete(autocomplete.Select2ListView):

    def get_list(self):
        if not self.request.user.is_staff:
            return []

        try:
            esp_device = Colonel.objects.get(
                pk=self.forwarded.get("colonel")
            )
        except:
            return []

        return get_gpio_pins_choices(
            esp_device, self.forwarded.get('filters'),
            self.forwarded.get('self')
        )


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
