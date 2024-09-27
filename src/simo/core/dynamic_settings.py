import os
from django.conf import settings
from dynamic_preferences.preferences import Section
from dynamic_preferences.types import (
    BooleanPreference, StringPreference, ChoicePreference, IntegerPreference,
)
from dynamic_preferences.registries import global_preferences_registry

core = Section('core')


@global_preferences_registry.register
class HubUID(StringPreference):
    section = core
    name = 'hub_uid'
    default = ''
    required = True


@global_preferences_registry.register
class HubSecret(StringPreference):
    section = core
    name = 'hub_secret'
    default = ''
    required = True


@global_preferences_registry.register
class RemoteHttp(StringPreference):
    section = core
    name = 'remote_http'
    default = ''
    required = False


@global_preferences_registry.register
class RemoteConnectionVersion(IntegerPreference):
    section = core
    name = 'remote_conn_version'
    default = 1
    required = True
    help_text = "Keeps track on vpn and remote configurations "\
                "when hub get's synced up to the simo.io."



@global_preferences_registry.register
class LatestHubOSVersionAvailable(StringPreference):
    section = core
    name = 'latest_version_available'
    default = '1.0.12'


@global_preferences_registry.register
class AutoUpdate(BooleanPreference):
    section = core
    name = 'auto_update'
    default = False

    def validate(self, value):
        if value:
            with open(os.path.join(settings.VAR_DIR, 'auto_update'), 'w') as f:
                f.write("YES!")
        else:
            try:
                os.remove(os.path.join(settings.VAR_DIR, 'auto_update'))
            except:
                pass
        return


@global_preferences_registry.register
class NeedsMqttAclsRebuild(BooleanPreference):
    section = core
    name = 'needs_mqtt_acls_rebuild'
    default = True