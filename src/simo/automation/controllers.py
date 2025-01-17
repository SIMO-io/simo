import time
import json
import requests
import traceback
import sys
import random
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from simo.conf import dynamic_settings
from simo.users.utils import get_current_user
from simo.core.models import RUN_STATUS_CHOICES_MAP, Component
from simo.core.utils.operations import OPERATIONS
from simo.core.middleware import get_current_instance
from simo.core.controllers import (
    BEFORE_SEND, BEFORE_SET, ControllerBase, TimerMixin,
)
from .gateways import AutomationsGatewayHandler
from .app_widgets import ScriptWidget
from .forms import (
    ScriptConfigForm, PresenceLightingConfigForm
)
from .state import get_current_state
from .serializers import UserSerializer


class Script(ControllerBase, TimerMixin):
    name = _("AI Script")
    base_type = 'script'
    gateway_class = AutomationsGatewayHandler
    app_widget = ScriptWidget
    config_form = ScriptConfigForm
    admin_widget_template = 'admin/controller_widgets/script.html'
    default_config = {'autostart': True, 'autorestart': True}
    default_value = 'stopped'
    masters_only = True

    def _validate_val(self, value, occasion=None):
        if occasion == BEFORE_SEND:
            if value not in ('start', 'stop'):
                raise ValidationError("Must be 'start' or 'stop'")
        elif occasion == BEFORE_SET:
            if value not in RUN_STATUS_CHOICES_MAP.keys():
                raise ValidationError(
                    "Invalid script controller status!"
                )
        return value

    def _prepare_for_send(self, value):
        if value == 'start':
            new_code = getattr(self.component, 'new_code', None)
            if new_code:
                self.component.new_code = None
                self.component.refresh_from_db()
                self.component.config['code'] = new_code
                self.component.save(update_fields=['config'])
        return value

    def _val_to_success(self, value):
        if value == 'start':
            return 'running'
        else:
            return 'stopped'

    def start(self, new_code=None):
        if new_code:
            self.component.new_code = new_code
        self.send('start')

    def play(self):
        return self.start()

    def stop(self):
        self.send('stop')

    def toggle(self):
        self.component.refresh_from_db()
        if self.component.value == 'running':
            self.send('stop')
        else:
            self.send('start')

    def ai_assistant(self, wish):
        try:
            request_data = {
                'hub_uid': dynamic_settings['core__hub_uid'],
                'hub_secret': dynamic_settings['core__hub_secret'],
                'instance_uid': get_current_instance().uid,
                'system_data': json.dumps(get_current_state()),
                'wish': wish,
            }
        except Exception as e:
            print(traceback.format_exc(), file=sys.stderr)
            return {'status': 'error', 'result': f"Internal error: {e}"}
        user = get_current_user()
        if user:
            request_data['current_user'] = UserSerializer(user, many=False).data
        try:
            response = requests.post(
                'https://simo.io/hubs/ai-assist/scripts/', json=request_data
            )
        except:
            return {'status': 'error', 'result': "Connection error"}

        if response.status_code != 200:
            content = response.content.decode()
            if '<html' in content:
                # Parse the HTML content
                soup = BeautifulSoup(response.content, 'html.parser')
                content = F"Server error {response.status_code}: {soup.title.string}"
            return {'status': 'error', 'result': content}

        return {
            'status': 'success',
            'result': response.json()['script'],
            'description': response.json()['description']
        }


class PresenceLighting(Script):
    masters_only = False
    name = _("Presence lighting")
    config_form = PresenceLightingConfigForm

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # script specific variables
        self.sensors = {}
        self.condition_comps = {}
        self.light_org_values = {}
        self.light_send_values = {}
        self.is_on = False
        self.turn_off_task = None
        self.last_presence = 0
        self.hold_time = 60
        self.conditions = []
        self.expected_light_values = {}

    def _run(self):
        self.hold_time = self.component.config.get('hold_time', 0) * 10
        for id in self.component.config['presence_sensors']:
            sensor = Component.objects.filter(id=id).first()
            if sensor:
                sensor.on_change(self._on_sensor)
                self.sensors[id] = sensor

        for light_params in self.component.config['lights']:
            light = Component.objects.filter(
                id=light_params.get('light')
            ).first()
            if not light or not light.controller:
                continue
            light.on_change(self._on_light_change)

        for condition in self.component.config.get('conditions', []):
            comp = Component.objects.filter(
                id=condition.get('component', 0)
            ).first()
            if comp:
                condition['component'] = comp
                condition['condition_value'] = \
                    comp.controller._string_to_vals(condition['value'])
                if condition['op'] != 'in':
                    condition['condition_value'] = \
                        condition['condition_value'][0]
                self.conditions.append(condition)
                comp.on_change(self._on_condition)
                self.condition_comps[comp.id] = comp

        while True:
            # Resend expected values if they have failed to reach
            # corresponding light
            for c_id, [timestamp, expected_val] in self.expected_light_values.items():
                if time.time() - timestamp < 5:
                    continue
                comp = Component.objects.filter(id=c_id).first()
                if not comp:
                    continue
                print(f"Resending [{expected_val}] to {comp}")
                comp.send(expected_val)
            self._regulate()
            time.sleep(random.randint(5, 15))

    def _on_sensor(self, sensor=None):
        if sensor:
            self.sensors[sensor.id] = sensor
            self._regulate(on_sensor=True)

    def _on_condition(self, condition_comp=None):
        if condition_comp:
            for condition in self.conditions:
                if condition['component'].id == condition_comp.id:
                    condition['component'] = condition_comp
            self._regulate(on_condition_change=True)

    def _on_light_change(self, light):
        # If we were expecting some value change from the light
        # We have received something. So we stop demanding it!
        self.expected_light_values.pop(light.id, None)
        # change original value if it has been changed to something different
        if self.is_on and light.value != self.light_send_values[light.id]:
            self.light_send_values[light.id] = light.value
            self.light_org_values[light.id] = light.value

    def _regulate(self, on_sensor=False, on_condition_change=False):
        presence_values = [s.value for id, s in self.sensors.items()]
        if self.component.config.get('act_on', 0) == 0:
            must_on = any(presence_values)
        else:
            must_on = all(presence_values)

        if must_on and on_sensor:
            print("Presence detected!")

        if must_on:
            self.last_presence = 0

        additional_conditions_met = True
        for condition in self.conditions:

            comp = condition['component']

            op = OPERATIONS.get(condition.get('op'))
            if not op:
                continue

            if condition['op'] == 'in':
                if comp.value not in condition['condition_value']:
                    if must_on and on_sensor:
                        print(
                            f"Condition not met: [{comp} value:{comp.value} "
                            f"{condition['op']} {condition['condition_value']}]"
                        )
                    additional_conditions_met = False
                    break

            if not op(comp.value, condition['condition_value']):
                if must_on and on_sensor:
                    print(
                        f"Condition not met: [{comp} value:{comp.value} "
                        f"{condition['op']} {condition['condition_value']}]"
                    )
                additional_conditions_met = False
                break

        if not self.is_on:
            if not must_on:
                return
            if not additional_conditions_met:
                return
            if on_condition_change:
                return

            print("Turn the lights ON!")
            self.is_on = True
            self.light_org_values = {}
            for light_params in self.component.config['lights']:
                comp = Component.objects.filter(
                    id=light_params.get('light')
                ).first()
                if not comp or not comp.controller:
                    continue
                self.light_org_values[comp.id] = comp.value
                on_val = light_params['on_value']
                if type(comp.controller.default_value) == bool:
                    on_val = bool(on_val)
                print(f"Send {on_val} to {comp}!")
                self.light_send_values[comp.id] = on_val
                if comp.value != on_val:
                    self.expected_light_values[comp.id] = [time.time(), on_val]
                comp.controller.send(on_val)
            return

        else:
            if not additional_conditions_met:
                return self._turn_it_off()
            if not any(presence_values):
                if not self.component.config.get('hold_time', 0):
                    return self._turn_it_off()

                if not self.last_presence:
                    self.last_presence = time.time()

                if self.hold_time and (
                    time.time() - self.hold_time > self.last_presence
                ):
                    self._turn_it_off()


    def _turn_it_off(self):
        print("Turn the lights OFF!")
        self.is_on = False
        self.last_presence = 0
        for light_params in self.component.config['lights']:
            comp = Component.objects.filter(
                id=light_params.get('light')
            ).first()
            if not comp or not comp.controller:
                continue
            try:
                off_val = int(light_params.get('off_value', 0))
            except:
                off_val = 0
            if off_val != 0:
                off_val = self.light_org_values.get(comp.id, 0)
            print(f"Send {off_val} to {comp}!")
            if comp.value != off_val:
                self.expected_light_values[comp.id] = [time.time(), off_val]
            comp.send(off_val)


# TODO: Night lighting
#
# Lights: components (switches, dimmers)
# On value: 40
# Sunset offset (mins): negative = earlier, positive = later
# Save energy at night: 1 - 6 turn the lights completely off at night.
