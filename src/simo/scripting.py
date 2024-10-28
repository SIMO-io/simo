from django.utils import timezone
from suntime import Sun
from simo.core.middleware import get_current_instance


class LocalSun(Sun):

    def __init__(self, instance=None):
        if not instance:
            instance = get_current_instance()
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







import time
from django.utils import timezone
from simo.core.models import Component
from simo.users.models import InstanceUser
from simo.generic.scripting.helpers import LocalSun


class Automation:
    rezimas = Component.objects.get(id=130)
    sun = LocalSun()
    last_rezimas = None
    weekdays_morning_hour = 8
    weekends_morning_hour = 9

    def check_away(self):
        return not bool(InstanceUser.objects.filter(
            is_active=True, at_home=True
        ).count())

    def calculate_appropriate_rezimas(self, nobody_at_home, is_night, localtime):
        if nobody_at_home:
            return 'away'
        if is_night and localtime.hour <= 23:
                return 'evening'

        if localtime.weekday() < 5 and localtime.hour <= self.weekdays_morning_hour:
            return 'night'

        if localtime.weekday() >= 5 and localtime.hour <= self.weekends_morning_hour:
            return 'night'

        return 'day'


    def get_new_rezimas(self, rezimas, nobody_at_home, is_night, localtime):
        # If rezimas component on vacation or in some other state
        # we do not interfere!
        if rezimas.value not in ('day', 'night', 'evening', 'away'):
            return
        should_be = self.calculate_appropriate_rezimas(
            nobody_at_home, is_night, localtime
        )
        if should_be != self.last_rezimas:
            self.last_rezimas = should_be
            return should_be


    def run(self):
        while True:
            self.rezimas.refresh_from_db()
            new_rezimas_value = self.get_new_rezimas(
                self.rezimas, self.check_away(),
                self.sun.is_night(), timezone.localtime()
            )
            if new_rezimas_value:
                self.rezimas.send(new_rezimas_value)
            time.sleep(10)




