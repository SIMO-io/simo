import time
import random
from django.utils import timezone
from simo.core.middleware import get_current_instance
from simo.core.models import Component
from simo.users.models import InstanceUser
from simo.automation.helpers import (
    get_day_evening_night_morning, LocalSun
)


class Automation:
    STATE_COMP_ID = {{ state_comp_id }}
    INACTIVITY_MINUTES = 30

    def __init__(self):
        self.instance = get_current_instance()
        self.state = Component.objects.get(id=self.STATE_COMP_ID)
        self.sensors_on_watch = set()
        self.last_sensor_action = time.time()
        self.sun = LocalSun(self.instance.location)

    def sensor_change(self, sensor=None):
        self.last_sensor_action = time.time()

    def check_away(self):
        if InstanceUser.objects.filter(
            is_active=True, at_home=True
        ).count():
            return False

        return (
            time.time() - self.last_sensor_action
        ) // 60 >= self.INACTIVITY_MINUTES

    def run(self):
        while True:
            for sensor in Component.objects.filter(
                base_type='binary-sensor',
                alarm_category='security'
            ):
                if sensor.id not in self.sensors_on_watch:
                    sensor.on_change(self.sensor_change)
                    self.sensors_on_watch.add(sensor.id)

            self.state.refresh_from_db()
            if self.check_away():
                if self.state.value != 'away':
                    print("AWAY!")
                    self.state.send('away')
            else:
                if self.state.value == 'away':
                    new_state = get_day_evening_night_morning(
                        self.sun, timezone.localtime()
                    )
                    print(f"{new_state.upper()}!")
                    self.state.send(new_state)
            time.sleep(random.randint(60, 120))