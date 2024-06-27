import datetime
from django.utils import timezone
from celeryc import celery_app


@celery_app.task
def clear_device_report_logs():
    from simo.core.models import Instance
    from .models import UserDeviceReportLog
    for instance in Instance.objects.all():
        UserDeviceReportLog.objects.filter(
            instance=instance,
            datetime__lt=timezone.now() - datetime.timedelta(
                days=instance.device_report_history_days
            )
        ).delete()


@celery_app.task
def rebuild_mqtt_acls():
    from simo.conf import dynamic_settings
    if dynamic_settings['core__needs_mqtt_acls_rebuild']:
        dynamic_settings['core__needs_mqtt_acls_rebuild'] = False
        from .utils import update_mqtt_acls
        update_mqtt_acls()


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(60 * 60, clear_device_report_logs.s())
    sender.add_periodic_task(30, rebuild_mqtt_acls.s())
