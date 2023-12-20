from django.utils import timezone
from suntime import Sun
from simo.core.models import Instance


class LocalSun(Sun):

    def __init__(self, instance=None):
        if not instance:
            instance = Instance.objects.all().first()
        coordinates = instance.location.split(',')
        try:
            lat = float(coordinates[0])
        except:
            lat = 0
        try:
            lon = float(coordinates[1])
        except:
            lon = 0
        super().__init__(lat, lon)

    def is_night(self):
        if timezone.now() > self.get_sunset_time():
            return True
        if timezone.now() < self.get_sunrise_time():
            return True
        return False

    def seconds_to_sunset(self):
        return (self.get_sunset_time() - timezone.now()).total_seconds()

    def seconds_to_sunrise(self):
        return (self.get_sunrise_time() - timezone.now()).total_seconds()






