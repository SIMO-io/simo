from rest_framework import viewsets
from .models import Sound
from .serializers import SoundSerializer


class SoundViewSet(viewsets.ReadOnlyModelViewSet):
    url = 'multimedia/sounds'
    basename = 'sounds'
    queryset = Sound.objects.all()
    serializer_class = SoundSerializer

