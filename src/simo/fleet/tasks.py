import datetime
from django.utils import timezone
from celeryc import celery_app
from .models import Colonel


@celery_app.task
def watch_colonels_connection():
    for colonel in Colonel.objects.filter(
        socket_connected=True,
        last_seen__lt=timezone.now() - datetime.timedelta(minutes=10)
    ):
        colonel.socket_connected = False
        colonel.save()

@celery_app.task
def look_for_updates():
    for colonel in Colonel.objects.all():
        colonel.check_for_upgrade()


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(60, watch_colonels_connection.s())
    sender.add_periodic_task(60 * 10, look_for_updates.s())
