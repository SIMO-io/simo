import datetime
from django.db.models import Prefetch
from django.utils import timezone
from simo.core.middleware import drop_current_instance
from celeryc import celery_app


@celery_app.task
def check_colonels_connected():
    from .models import Colonel
    drop_current_instance()
    for lost_colonel in Colonel.objects.filter(
        socket_connected=True,
        last_seen__lt=timezone.now() - datetime.timedelta(seconds=20)
    ):
        lost_colonel.socket_connected = False
        lost_colonel.save()


@celery_app.task
def check_colonel_components_alive():
    from simo.core.models import Component
    from .models import Colonel
    drop_current_instance()
    for lost_colonel in Colonel.objects.filter(
        last_seen__lt=timezone.now() - datetime.timedelta(seconds=60)
    ).prefetch_related(Prefetch(
        'components', queryset=Component.objects.filter(alive=True),
        to_attr='alive_components'
    )):
        for comp in lost_colonel.alive_components:
            print(f"{comp} is no longer alive!")
            comp.alive = False
            comp.save()


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(10, check_colonels_connected.s())
    sender.add_periodic_task(20, check_colonel_components_alive.s())