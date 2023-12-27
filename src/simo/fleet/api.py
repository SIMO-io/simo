from rest_framework import viewsets
from simo.core.api import InstanceMixin
from .models import InstanceOptions
from .serializers import InstanceOptionsSerializer


class InstanceOptionsViewSet(InstanceMixin, viewsets.ReadOnlyModelViewSet):
    url = 'fleet/options'
    basename = 'fleet-options'
    serializer_class = InstanceOptionsSerializer

    def get_queryset(self):
        return InstanceOptions.objects.filter(instance=self.instance)
