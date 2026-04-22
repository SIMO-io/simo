import datetime
from django.db import transaction
from django.utils import timezone
from simo.core.middleware import (
    get_current_instance, drop_current_instance, introduce_instance
)
from .models import Notification, UserNotification


def dispatch_notification_now(notification_id):
    notification = Notification.objects.filter(
        id=notification_id,
        cancelled__isnull=True,
        is_pending=False,
    ).first()
    if not notification:
        return
    notification.dispatch()


def schedule_notification_dispatch(notification_id, countdown=0, using='default'):
    def _dispatch():
        if countdown and countdown > 0:
            from .tasks import dispatch_notification
            dispatch_notification.apply_async(args=[notification_id], countdown=countdown)
        else:
            dispatch_notification_now(notification_id)

    transaction.on_commit(_dispatch, using=using)


def create_notification(
    severity, title, body=None, component=None, instance_users=None,
    instance=None, dispatch=True, dispatch_countdown=0, event_key=None,
):
    '''
    Persist a notification and its recipients.

    :param severity: One of: 'info', 'warning', 'alarm'
    :param title: A short, descriptive title of the event.
    :param body: (Optional) A more detailed description of the event.
    :param component: (Optional) simo.core.Component linked to this event.
    :param instance_users: List of instance users to receive this notification. All active instance users will receive the message if not specified.
    :param dispatch: When True, schedule delivery after transaction commit.
    :param dispatch_countdown: Delay external delivery by N seconds.
    :param event_key: Optional durable source-event identifier.
    '''
    current_instance = get_current_instance()
    if not instance:
        if component:
            instance = component.zone.instance
        else:
            instance = get_current_instance()
    if not instance:
        return
    drop_current_instance()
    try:
        if component and component.zone.instance != instance:
            # something is completely wrong!
            return
        assert severity in ('info', 'warning', 'alarm')
        dispatch_after = None
        is_pending = False
        if dispatch_countdown and dispatch_countdown > 0:
            dispatch_after = timezone.now() + datetime.timedelta(seconds=dispatch_countdown)
            is_pending = True
        notification = Notification.objects.create(
            instance=instance,
            title=f'{instance.name}: {title}',
            severity=severity, body=body,
            component=component,
            is_pending=is_pending,
            dispatch_after=dispatch_after,
            event_key=event_key,
        )
        if instance_users is None:
            instance_users = instance.instance_users.filter(
                is_active=True
            ).select_related('user')
        for iuser in instance_users:
            # do not send emails to system users
            if iuser.user.email.endswith('simo.io'):
                continue
            if iuser.instance.id != instance.id:
                continue
            if component is not None and not iuser.can_read(component):
                continue
            UserNotification.objects.create(
                user=iuser.user, notification=notification,
            )
        if dispatch:
            using = getattr(getattr(notification, '_state', None), 'db', None) or 'default'
            schedule_notification_dispatch(
                notification.id,
                countdown=dispatch_countdown,
                using=using,
            )
        return notification
    finally:
        if current_instance:
            introduce_instance(current_instance)


def notify_users(severity, title, body=None, component=None, instance_users=None, instance=None):
    return create_notification(
        severity=severity,
        title=title,
        body=body,
        component=component,
        instance_users=instance_users,
        instance=instance,
        dispatch=True,
    )
