import time
import random
from django.utils import timezone
from simo.core.middleware import get_current_instance
from simo.core.models import Component
from simo.users.models import InstanceUser
from simo.automation.helpers import (
    LocalSun, get_day_evening_night_morning
)


class Automation:
    STATE_COMPONENT_ID = {{ state_comp_id }}

    def __init__(self):
        self.instance = get_current_instance()
        self.state = Component.objects.get(id=self.STATE_COMPONENT_ID)
        self.sun = LocalSun(self.instance.location)
        self.sleep_is_on = False

    def check_owner_phones(self, state, instance_users, datetime):
        if not self.sleep_is_on:
            if not (datetime.hour >= 21 or datetime.hour < 6):
                return

            for iuser in instance_users:
                # ignoring inactive and non owner users
                if not iuser.is_active or not iuser.role.is_owner:
                    continue
                # skipping users that are not at home
                if not iuser.at_home:
                    continue
                if not iuser.phone_on_charge:
                    # at least one user's phone is not yet on charge
                    return
            self.sleep_is_on = True
            print("Let's turn on the sleep mode!")
            return 'sleep'
        else:
            if datetime.hour >= 22 or datetime.hour < 6:
                return
            # return new_state diena only if there are still users
            # at home, none of them have their phones on charge
            # and current state is still night
            for iuser in instance_users:
                # ignoring inactive and non owner users
                if not iuser.is_active or not iuser.role.is_owner:
                    continue
                # skipping users that are not at home
                if not iuser.at_home:
                    continue
                if iuser.phone_on_charge:
                    # at least one user's phone is still on charge
                    return

            self.sleep_is_on = False

            if not self.sleep_is_on and state.value == 'sleep':
                new_state = get_day_evening_night_morning(
                    self.sun, timezone.localtime()
                )
                print(f"Switch state back to {new_state}!")
                return new_state

    def run(self):
        while True:
            instance_users = InstanceUser.objects.filter(
                is_active=True, role__is_owner=True
            ).prefetch_related('role')
            self.state.refresh_from_db()
            new_state = self.check_owner_phones(
                self.state, instance_users, timezone.localtime()
            )
            if new_state:
                self.state.send(new_state)

            # randomize script check times
            time.sleep(random.randint(20, 40))