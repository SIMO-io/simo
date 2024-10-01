from dynamic_preferences.preferences import Section
from dynamic_preferences.types import (
    BooleanPreference, StringPreference, ChoicePreference, IntegerPreference,
)
from dynamic_preferences.registries import global_preferences_registry

backups = Section('backups')


@global_preferences_registry.register
class LastBackupError(StringPreference):
    section = backups
    name = 'last_error'
    default = ''


@global_preferences_registry.register
class LastBackupCheck(IntegerPreference):
    section = backups
    name = 'last_check'
    default = 0