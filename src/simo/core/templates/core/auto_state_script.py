import time
from django.utils import timezone
from simo.core.middleware import get_current_instance
from simo.core.models import Component
from simo.users.models import InstanceUser
from simo.generic.scripting.helpers import LocalSun


class Automation:
    STATE_COMPONENT_ID = {{ state_comp_id }}
    last_state = None
    weekdays_morning_hour = 10
    weekends_morning_hour = 11

    def __init__(self):
        self.instance = get_current_instance()
        self.state = Component.objects.get(id=self.STATE_COMPONENT_ID)
        self.sun = LocalSun(self.instance.location)

    def check_at_home(self):
        return bool(InstanceUser.objects.filter(
            is_active=True, at_home=True
        ).count())

    def calculate_appropriate_state(self, localtime, at_home):
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

    def get_new_state(self, state, localtime, at_home):
        # If state component on vacation or in some other state
        # we do not interfere!
        if state.value not in ('day', 'night', 'evening', 'away'):
            return
        should_be = self.calculate_appropriate_state(
            localtime, at_home
        )

        if self.last_state != state.value:
            # user changed something manually
            # we must first wait for appropriate state to get in to
            # manually selected one, only then we will transition to forward.
            if should_be == state.value:
                print("Consensus with system users reached!")
                self.last_state = should_be
        elif self.last_state != should_be:
            print("New state: ", should_be)
            self.last_state = should_be
            return should_be

    def run(self):
        # do not interfere on script start, 
        # only later when we absolutely must
        self.last_state = self.get_new_state(
            self.state, timezone.localtime(),
            self.check_at_home()
        )
        while True:
            self.state.refresh_from_db()
            new_state_value = self.get_new_state(
                self.state, timezone.localtime(),
                self.check_at_home()
            )
            if new_state_value:
                self.state.send(new_state_value)
            time.sleep(10)