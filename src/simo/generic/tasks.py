import sys, traceback, time
from django.db import transaction
from django.utils import timezone
from celeryc import celery_app
from simo.core.middleware import drop_current_instance


@celery_app.task
def notify_users_on_alarm_group_breach(notification_id, ag_id, breach_transition_id=None):
    from simo.core.models import Component
    from simo.notifications.models import Notification
    from simo.notifications.utils import dispatch_notification_now

    drop_current_instance()
    with transaction.atomic():
        notification = Notification.objects.select_for_update().filter(
            id=notification_id
        ).first()
        if not notification:
            return
        if notification.cancelled:
            return
        if not notification.is_pending:
            return
        ag = Component.objects.select_for_update().filter(id=ag_id).first()
        if not ag:
            notification.cancelled = timezone.now()
            notification.is_pending = False
            notification.save(update_fields=['cancelled', 'is_pending'])
            return
        current_transition_id = ag.meta.get('breach_transition_id')
        if breach_transition_id and current_transition_id != breach_transition_id:
            notification.cancelled = timezone.now()
            notification.is_pending = False
            notification.save(update_fields=['cancelled', 'is_pending'])
            return
        if ag.value != 'breached':
            notification.cancelled = timezone.now()
            notification.is_pending = False
            notification.save(update_fields=['cancelled', 'is_pending'])
            return
        notification.is_pending = False
        notification.save(update_fields=['is_pending'])

    dispatch_notification_now(notification_id)


@celery_app.task
def fire_breach_events(ag_id):
    from simo.core.models import Component
    drop_current_instance()
    ag = Component.objects.filter(id=ag_id).first()
    if not ag:
        return
    if ag.value != 'breached':
        # no longer breached, somebody disarmed it,
        # no need to send any notifications
        return
    for uid, event in ag.controller.events_map.items():
        if uid in ag.meta.get('events_triggered', []):
            continue
        threshold = event.get('threshold', 1)
        if len(ag.meta['breach_times']) < threshold:
            continue
        if time.time() - ag.meta['breach_times'][threshold - 1] < event['delay']:
            continue
        try:
            getattr(event['component'], event['breach_action'])()
        except Exception:
            print(traceback.format_exc(), file=sys.stderr)
        if not ag.meta.get('events_triggered'):
            ag.meta['events_triggered'] = [uid]
        else:
            ag.meta['events_triggered'].append(uid)
        ag.save(update_fields=['meta'])
