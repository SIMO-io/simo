from celeryc import celery_app


@celery_app.task
def dispatch_notification(notification_id):
    from django.db import transaction
    from .models import Notification
    from .utils import dispatch_notification_now

    with transaction.atomic():
        notification = Notification.objects.select_for_update().filter(
            id=notification_id,
            cancelled__isnull=True,
        ).first()
        if not notification:
            return
        if notification.is_pending:
            notification.is_pending = False
            notification.save(update_fields=['is_pending'])

    dispatch_notification_now(notification_id)
