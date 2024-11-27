import time
import random
from django.utils import timezone
from simo.core.middleware import get_current_instance
from simo.core.models import Component
from simo.automation.helpers import (
    LocalSun, get_day_evening_night_morning
)


class Automation:
    STATE_COMPONENT_ID = {{ state_comp_id }}

    def __init__(self):
        self.state = Component.objects.get(id=self.STATE_COMPONENT_ID)
        self.sun = LocalSun(get_current_instance().location)

    def run(self):
        while True:
            self.state.refresh_from_db()
            if self.state.value in ('day', 'night', 'evening', 'morning'):

                current_state = get_day_evening_night_morning(
                    self.sun, timezone.localtime()
                )
                if current_state != self.state.value:
                    print(f"New state - {current_state}")
                    self.state.send(current_state)

            # randomize script check times
            time.sleep(random.randint(20, 40))