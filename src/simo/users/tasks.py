import datetime
from celeryc import celery_app
from django.utils import timezone
from .models import User


@celery_app.task
def watch_users_at_home():
    # Treat users as no longer at home if we do not receive reports from
    # it's primary device for more than 10 minutes.
    for user in User.objects.filter(instance_roles__at_home=True):
        user_device = user.devices.filter(is_primary=True).first()
        if not user_device:
            continue
        if not user_device.report_logs.filter(
            datetime__gt=timezone.now() - datetime.timedelta(minutes=10)
        ):
            user.instance_roles.all().update(at_home=False)


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(60, watch_users_at_home.s())



