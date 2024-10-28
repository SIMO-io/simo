import datetime
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

    def get_sunrise_time(self, localdatetime=None):
        if localdatetime:
            utc_datetime = localdatetime.astimezone(pytz.utc)
        else:
            utc_datetime = None
        sunrise = super().get_sunrise_time(date=utc_datetime)
        if not localdatetime or not localdatetime.tzinfo:
            return sunrise
        return sunrise.astimezone(localdatetime.tzinfo)

    def get_sunset_time(self, localdatetime=None):
        if localdatetime:
            utc_datetime = localdatetime.astimezone(pytz.utc)
        else:
            utc_datetime = None
        sunset = super().get_sunset_time(date=utc_datetime)
        if not localdatetime or not localdatetime.tzinfo:
            return sunset
        return sunset.astimezone(localdatetime.tzinfo)

    def _get_utc_datetime(self, localdatetime=None):
        if not localdatetime:
            utc_datetime = timezone.now()
        else:
            utc_datetime = localdatetime.astimezone(pytz.utc)
        return utc_datetime

    def is_night(self, localdatetime=None):
        utc_datetime = self._get_utc_datetime(localdatetime)
        if utc_datetime > self.get_sunset_time(utc_datetime):
            return True
        if utc_datetime < self.get_sunrise_time(utc_datetime):
            return True
        return False

    def seconds_to_sunset(self, localdatetime=None):
        utc_datetime = self._get_utc_datetime(localdatetime)
        return (self.get_sunset_time(utc_datetime) - utc_datetime).total_seconds()

    def seconds_to_sunrise(self, localdatetime=None):
        utc_datetime = self._get_utc_datetime(localdatetime)
        return (self.get_sunrise_time(utc_datetime) - utc_datetime).total_seconds()


