import datetime
from django.utils import timezone
from celeryc import celery_app


@celery_app.task
def auto_expire_tokens():
    """Auto expire instance access tokens that are older than one day"""
    from .models import InstanceAccessToken
    InstanceAccessToken.objects.filter(
        date_created__lt=timezone.now() - datetime.timedelta(days=1),
        date_expired=None
    ).update(date_expired=timezone.now())



@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(60 * 60, auto_expire_tokens.s()) # hourly cron