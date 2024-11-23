import pytz
import math
import time
import random
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
        sunrise = super().get_sunrise_time(date=localdatetime)
        if not localdatetime or not localdatetime.tzinfo:
            return sunrise
        return sunrise.astimezone(localdatetime.tzinfo)

    def get_sunset_time(self, localdatetime=None):
        sunset = super().get_sunset_time(date=localdatetime)
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


def get_day_evening_night_morning(sun, localtime):

    # It is daytime if the sun is up!
    if not sun.is_night():
        return 'day'

    # it is evening if the sun is down at the evening
    if sun.get_sunset_time(localtime) < localtime:
        return 'evening'

    # if it's past 6 AM but still dark - we consider this as morning
    if localtime.hour >= 6:
        return 'morning'

    # 0 - 6AM and still dark
    return 'night'


def haversine_distance(location1, location2, units_of_measure='metric'):
    # Radius of Earth in meters
    R = 6371000

    # Unpack coordinates
    lat1, lon1 = location1.split(',')
    lat2, lon2 = location2.split(',')
    lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)

    # Convert latitude and longitude from degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    # Haversine formula
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(
        phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    # Distance in meters
    distance_meters = R * c

    # Convert to feet if 'imperial' is chosen
    if units_of_measure == 'imperial':
        distance = distance_meters * 3.28084  # Convert meters to feet
    else:
        distance = distance_meters  # Keep in meters for 'metric'

    return distance


def be_or_not_to_be(min_seconds, max_seconds, last_be_timestamp=0):
    '''
    Returns True if max_hours has passed after last_be or last_be is not provided
    Returns False if min_hours not yet passed
    Returns True or False if if last_be is in betwen of min_hours and max_hours
    with rising probability of Trye from 0% (min_hours) to 100% (max_hours)
    '''
    if last_be_timestamp:
        seconds_since_last = time.time() - last_be_timestamp
    else:
        seconds_since_last = max_seconds

    if seconds_since_last >= max_seconds:
        return True
    if seconds_since_last >= min_seconds:  # Calculate probability after min_hours hours
        probability = min((seconds_since_last - min_seconds) / (max_seconds - min_seconds), 1.0)
        return random.random() < probability
    return False