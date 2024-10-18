from simo.users.models import User
from .models import Notification, UserNotification


def notify_users(instance, severity, title, body=None, component=None, users=None):
    '''
    Sends a notification to specified users with a given severity level and message details.
    :param instance: simo.core.models.Instance instance
    :param severity: One of: 'info', 'warning', 'alarm'
    :param title: A short, descriptive title of the event.
    :param body: (Optional) A more detailed description of the event.
    :param component: (Optional) simo.core.Component linked to this event.
    :param users: List of users to receive this notification. All active instance users will receive the message if not specified.
    :return:
    '''
    assert severity in ('info', 'warning', 'alarm')
    notification = Notification.objects.create(
        instance=instance,
        title=f'{instance.name}: {title}',
        severity=severity, body=body,
        component=component
    )
    if not users:
        users = User.objects.filter(
            instance_roles__instance=instance,
            instance_roles__is_active=True
        )
    for user in users:
        # do not send emails to system users
        if user.email.endswith('simo.io'):
            continue
        if instance not in user.instances:
            continue
        if component and not component.can_write(user):
            continue
        UserNotification.objects.create(
            user=user, notification=notification,
        )
    notification.dispatch()
