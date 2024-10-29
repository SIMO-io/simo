import time
import pytz
from datetime import datetime
from django.utils import timezone
from simo.core.middleware import get_current_instance
from simo.core.models import Component
from simo.users.models import InstanceUser
from simo.generic.scripting.helpers import LocalSun


class Automation:
    last_rezimas = None
    weekdays_morning_hour = 8
    weekends_morning_hour = 9

    def __init__(self):
        self.instance = get_current_instance()
        self.rezimas = Component.objects.get(id=130)
        self.sun = LocalSun(self.instance.location)

    def check_at_home(self):
        return bool(InstanceUser.objects.filter(
            is_active=True, at_home=True
        ).count())

    def calculate_appropriate_rezimas(self, localtime, at_home):
        if not at_home:
            return 'away'
        if self.sun.is_night(localtime) \
        and self.sun.get_sunset_time(localtime) < localtime:
            return 'evening'

        if localtime.weekday() < 5 \
        and localtime.hour < self.weekdays_morning_hour:
            return 'night'

        if localtime.weekday() >= 5 \
        and localtime.hour < self.weekends_morning_hour:
            return 'night'

        return 'day'

    def get_new_rezimas(self, rezimas, localtime, at_home):
        # If rezimas component on vacation or in some other state
        # we do not interfere!
        if rezimas.value not in ('day', 'night', 'evening', 'away'):
            return
        should_be = self.calculate_appropriate_rezimas(
            localtime, at_home
        )

        print("Should be: ", should_be)

        if rezimas.value != self.last_rezimas:
            # user changed something manually
            # we must first wait for appropriate rezimas to get in to
            # manually selected one, only then we will transition to forward.
            print("User has his own rezimas set")
            if should_be == rezimas.value:
                print("We have reached consensus with user.")
                self.last_rezimas = should_be
        elif self.last_rezimas != should_be:
            print("New rezimas: ", should_be)
            self.last_rezimas = should_be
            return should_be

    def run(self):
        # do not interfere on script start, only later when we absolutely must
        self.last_rezimas = self.get_new_rezimas(
            self.rezimas, timezone.localtime(),
            self.check_at_home()
        )
        while True:
            self.rezimas.refresh_from_db()
            new_rezimas_value = self.get_new_rezimas(
                self.rezimas, timezone.localtime(),
                self.check_at_home()
            )
            if new_rezimas_value:
                self.rezimas.send(new_rezimas_value)
            time.sleep(10)

    def test(self):
        self.sun = LocalSun('54.9045351,23.889193')
        self.last_rezimas = 'day'
        self.rezimas.value = 'day'
        tz = pytz.timezone(self.instance.timezone)

        # Daytime, nobody's at home
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 24, 11)),
            at_home=False
        ) == 'away'

        # User manually changed rezimas
        self.rezimas.value = 'evening'
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 24, 13)),
            at_home=False
        ) == None

        # Somebody came home,
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 24, 14)),
            at_home=True
        ) == None

        # Actual evening
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 24, 21)),
            at_home=True
        ) == None

        # Night has come
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 25, 0)),
            at_home=True
        ) == 'night'
        # simulate rezimas has been changed
        self.rezimas.value = 'night'

        # User manually changed this to day earlier than expected
        self.rezimas.value = 'day'
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 25, 6)),
            at_home=True
        ) == None

        # Nothing needs to be changed, we are in day already
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 25, 8)),
            at_home=True
        ) == None

        # Everyone left
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 25, 9)),
            at_home=False
        ) == 'away'
        # simulate rezimas has been changed
        self.rezimas.value = 'away'

        # Everyone are still left
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 25, 10)),
            at_home=False
        ) == None

        # Someone came back
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 25, 14)),
            at_home=True
        ) == 'day'
        # simulate rezimas has been changed
        self.rezimas.value = 'day'

        # Evening
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 25, 19)),
            at_home=True
        ) == 'evening'
        # simulate rezimas has been changed
        self.rezimas.value = 'evening'

        # Nothing is changed
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 25, 20)),
            at_home=True
        ) == None

        # It's friday night, everyone is out!
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 25, 21)),
            at_home=False
        ) == 'away'
        # simulate rezimas has been changed
        self.rezimas.value = 'away'

        # Everyone is stil out!
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 26, 1)),
            at_home=False
        ) == None

        # Someone came back home straight to the bed!
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 26, 2)),
            at_home=True
        ) == 'night'
        # simulate rezimas has been changed
        self.rezimas.value = 'night'

        # It's weekend, day comes later!
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 26, 8)),
            at_home=True
        ) == None

        # Right about now!
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 26, 9)),
            at_home=True
        ) == 'day'
        # simulate rezimas has been changed
        self.rezimas.value = 'day'

        # But home owners want to continue sleeping so they set this back to night
        # and we do not interfere
        self.rezimas.value = 'night'
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 26, 9, 20)),
            at_home=True
        ) == None

        # Not even later in the day, it's beena heck of a party...
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 26, 13)),
            at_home=True
        ) == None

        # Not even later in the evening...
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 26, 20)),
            at_home=True
        ) == None

        # Now it's night again, but we do nothing
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 27, 1)),
            at_home=True
        ) == None

        # Now it's night again, but we do nothing
        # but when next morning comes, we can safely set it to day
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 27, 10)),
            at_home=True
        ) == 'day'
        # simulate rezimas has been changed
        self.rezimas.value = 'day'

        # Now user went on vacation, so we must not change anything until
        # he is back
        self.rezimas.value = 'vacation'
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 27, 20)),
            at_home=False
        ) == None

        # Not even at night
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 28, 1)),
            at_home=False
        ) == None

        # Nor next day
        assert self.get_new_rezimas(
            self.rezimas, tz.localize(datetime(2024, 10, 28, 12)),
            at_home=False
        ) == None


automation = Automation()
automation.test()
automation.run()