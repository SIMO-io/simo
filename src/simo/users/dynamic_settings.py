from dynamic_preferences.preferences import Section
from dynamic_preferences.types import (
    BooleanPreference, StringPreference, ChoicePreference, IntegerPreference,
    FilePreference
)
from dynamic_preferences.registries import global_preferences_registry

users = Section('users')


@global_preferences_registry.register
class AtHomeRadius(IntegerPreference):
    section = users
    name = 'at_home_radius'
    default = 250
    required = True
    help_text = 'Distance in meters around hub location point that is ' \
                'considered as At Home.'


