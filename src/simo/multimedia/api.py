from rest_framework import viewsets
from simo.core.api import InstanceMixin
from django.conf import settings
from .models import Sound
from .serializers import SoundSerializer


class SoundViewSet(InstanceMixin, viewsets.ReadOnlyModelViewSet):
    url = 'multimedia/sounds'
    basename = 'sounds'
    serializer_class = SoundSerializer

    def get_queryset(self):
        if getattr(settings, 'IS_VIRTUAL', False):
            return Sound.objects.none()
        return Sound.objects.filter(instance=self.instance)
