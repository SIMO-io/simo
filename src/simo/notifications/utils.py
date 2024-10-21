from simo.core.middleware import get_current_instance
from .models import Notification, UserNotification


def notify_users(severity, title, body=None, component=None, instance_users=None, instance=None):
    '''
    Sends a notification to specified users with a given severity level and message details.
    :param severity: One of: 'info', 'warning', 'alarm'
    :param title: A short, descriptive title of the event.
    :param body: (Optional) A more detailed description of the event.
    :param component: (Optional) simo.core.Component linked to this event.
    :param instance_users: List of instance users to receive this notification. All active instance users will receive the message if not specified.
    :return:
    '''
    if not instance:
        if component:
            instance = component.zone.instance
        else:
            instance = get_current_instance()
    if not instance:
        return
    if component and component.zone.instance != instance:
        # something is completely wrong!
        return
    assert severity in ('info', 'warning', 'alarm')
    notification = Notification.objects.create(
        instance=instance,
        title=f'{instance.name}: {title}',
        severity=severity, body=body,
        component=component
    )
    if not instance_users:
        instance_users = instance.instance_users.filter(
            is_active=True
        ).select_related('user')
    for iuser in instance_users:
        # do not send emails to system users
        if iuser.user.email.endswith('simo.io'):
            continue
        if iuser.instance.id != instance.id:
            continue
        if component and not component.can_read(iuser.user):
            continue
        UserNotification.objects.create(
            user=iuser.user, notification=notification,
        )
    notification.dispatch()
