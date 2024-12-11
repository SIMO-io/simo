from django.http import Http404
from dal import autocomplete
from simo.core.utils.helpers import search_queryset
from .models import Sound


class SoundAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            raise Http404()

        qs = Sound.objects.all()

        if self.request.GET.get('value'):
            qs = qs.filter(pk__in=self.request.GET['value'].split(','))
        elif self.q:
            qs = search_queryset(qs, self.q, ('name', 'slug'))
        return qs