import sys, traceback, time
from celeryc import celery_app
from simo.core.middleware import drop_current_instance, drop_current_instance


@celery_app.task
def notify_users_on_alarm_group_breach(ag_id):
    from simo.core.models import Component
    drop_current_instance()
    ag = Component.objects.filter(id=ag_id).first()
    if not ag:
        return
    if ag.value != 'breached':
        # no longer breached, somebody disarmed it,
        # no need to send any notifications
        return

    breached_components = Component.objects.filter(
        pk__in=ag.config['components'],
        arm_status='breached'
    )
    body = "Security Breach! " + '; '.join(
        [str(c) for c in breached_components]
    )
    from simo.notifications.utils import notify_users
    notify_users(
        'alarm', str(ag), body, component=ag,
        instance=ag.zone.instance
    )


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


@celery_app.task
def watch_timers():
    from simo.core.models import Component
    drop_current_instance()
    for component in Component.objects.filter(
        meta__timer_to__gt=0
    ).filter(meta__timer_to__lt=time.time()):
        component.meta['timer_to'] = 0
        component.meta['timer_start'] = 0
        component.save()
        try:
            component.controller._on_timer_end()
        except Exception as e:
            print(traceback.format_exc(), file=sys.stderr)


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(1, watch_timers.s())