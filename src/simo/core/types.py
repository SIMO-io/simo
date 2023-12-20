import importlib
from django.utils.translation import gettext_lazy as _
from django.apps import apps


COMPONENT_TYPE_CHOICES = (
    ('dummy', _("Dummy")),
    ('on/off-sensor', _("On/Off sensor")),
    ('presence-sensor', _("Presence sensor")),
    ('door-sensor', _("Door sensor")),
    ('motion-sensor', _("Motion sensor")),
    ('temperature-sensor', _("Temperature sensor")),
    ('o2-sensor', _("O2 sensor")),
    ('flood-sensor', _("Flood sensor")),
    ('humidity-sensor', _("Humidity sensor")),

    ('switch', _("Switch")),
    ('dimmer', _("Dimmer")),
    ('rgb-led', _("RGBW Led")),
    ('rgbw-led', _("RGBW Led")),
    ('lock', _("Lock"))
)

# Add more types from other apps
for name, app in apps.app_configs.items():
    if name in (
        'core', 'auth', 'admin', 'contenttypes', 'sessions', 'messages',
        'staticfiles'
    ):
        continue
    try:
        controllers = importlib.import_module('%s.types' % name)
    except:
        continue
    for name, var in controllers.__dict__.items():
        if name == 'COMPONENT_TYPE_CHOICES':
            COMPONENT_TYPE_CHOICES += var