from django.utils.translation import gettext_lazy as _
from simo.core.app_widgets import BaseAppWidget


class ScriptWidget(BaseAppWidget):
    uid = 'script'
    name = _("Script")
    size = [2, 1]


class ThermostatWidget(BaseAppWidget):
    uid = 'thermostat'
    name = _("Thermostat")
    size = [2, 2]


class AlarmClockWidget(BaseAppWidget):
    uid = 'alarm-clock'
    name = _("Alarm clock")
    size = [2, 2]


class AlarmGroupWidget(BaseAppWidget):
    uid = 'alarm-group'
    name = _("Alarm group")
    size = [4, 1]


class IPCameraWidget(BaseAppWidget):
    uid = 'ip-camera'
    name = _("IP camera")
    size = [2, 2]


class WeatherWidget(BaseAppWidget):
    uid = 'weather'
    name = _("Weather")
    size = [4, 2]


class WateringWidget(BaseAppWidget):
    uid = 'watering'
    name = _('Watering')
    size = [2, 2]


class StateSelectWidget(BaseAppWidget):
    uid = 'state-select'
    name = _('State Select')
    size = [4, 1]
