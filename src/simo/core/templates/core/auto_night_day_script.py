import time
import random
from django.utils import timezone
from simo.core.middleware import get_current_instance
from simo.core.models import Component
from simo.users.models import InstanceUser
from simo.generic.scripting.helpers import LocalSun


class Automation:
    STATE_COMPONENT_ID = {{ state_comp_id }}

    def __init__(self):
        self.instance = get_current_instance()
        self.state = Component.objects.get(id=self.STATE_COMPONENT_ID)
        self.sun = LocalSun(self.instance.location)
        self.night_is_on = False

    def check_owner_phones(self, state, instance_users, datetime):
        if not self.night_is_on:
            if not (datetime.hour >= 22 or datetime.hour < 6):
                return

            for iuser in instance_users:
                # skipping users that are not at home
                if not iuser.at_home:
                    continue
                if not iuser.phone_on_charge:
                    # at least one user's phone is not yet on charge
                    return
            self.night_is_on = True
            print("Night!")
            return 'night'
        else:
            if datetime.hour >= 22 or datetime.hour < 6:
                return
            # return new_state diena only if there are still users
            # at home, none of them have their phones on charge
            # and current state is still night
            for iuser in instance_users:
                # skipping users that are not at home
                if not iuser.at_home:
                    continue
                if iuser.phone_on_charge:
                    # at least one user's phone is still on charge
                    return

            self.night_is_on = False
            if not self.night_is_on and state.value == 'night':
                print("Day has come!")
                return 'day'

    def run(self):
        while True:
            instance_users = InstanceUser.objects.filter(
                is_active=True, role__is_owner=True
            )
            self.state.refresh_from_db()
            new_state = self.check_owner_phones(
                self.state, instance_users, timezone.localtime()
            )
            if new_state:
                self.state.send(new_state)

            # randomize script load
            time.sleep(random.randint(20, 40))