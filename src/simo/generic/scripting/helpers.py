import pytz
from django.utils import timezone
from suntime import Sun
from simo.core.models import Instance


class LocalSun(Sun):

    def __init__(self, location=None):
        if not location:
            instance = Instance.objects.all().first()
            coordinates = instance.location.split(',')
        else:
            coordinates = location.split(',')
        try:
            lat = float(coordinates[0])
        except:
            lat = 0
        try:
            lon = float(coordinates[1])
        except:
            lon = 0
        super().__init__(lat, lon)

    def _get_utc_time(self, localtime=None):
        if not localtime:
            utc_time = timezone.now()
        else:
            utc_time = localtime.astimezone(pytz.utc)
        return utc_time

    def is_night(self, localtime=None):
        utc_time = self._get_utc_time(localtime)
        if utc_time > self.get_sunset_time():
            return True
        if utc_time < self.get_sunrise_time():
            return True
        return False

    def seconds_to_sunset(self, localtime=None):
        utc_time = self._get_utc_time(localtime)
        return (self.get_sunset_time() - utc_time).total_seconds()

    def seconds_to_sunrise(self, localtime=None):
        utc_time = self._get_utc_time(localtime)
        return (self.get_sunrise_time() - utc_time).total_seconds()


