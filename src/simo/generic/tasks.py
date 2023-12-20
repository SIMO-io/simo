import pytz
from django.utils import timezone
from celeryc import celery_app
from simo.core.models import Component
from .controllers import Thermostat, Script, Watering


# Moved to gateway
# @celery_app.task
# def watch_thermostats():
#     for thermostat in Component.objects.filter(
#         controller_uid=Thermostat.uid
#     ):
#         thermostat.evaluate()

@celery_app.task
def watch_failed_scripts():
    for script in Component.objects.filter(
        controller_uid=Script.uid, config__autorestart=True,
        value='error'
    ):
        tz = pytz.timezone(script.zone.instance.timezone)
        timezone.activate(tz)
        script.start()

@celery_app.task
def watch_watering():
    for watering in Component.objects.filter(controller_uid=Watering.uid):
        tz = pytz.timezone(watering.zone.instance.timezone)
        timezone.activate(tz)
        if watering.value['status'] == 'running_program':
            watering.set_program_progress(watering.value['program_progress'] + 1)
        else:
            watering.controller._perform_schedule()


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    # sender.add_periodic_task(60, watch_thermostats.s())
    sender.add_periodic_task(60, watch_failed_scripts.s())
    sender.add_periodic_task(60, watch_watering.s())
