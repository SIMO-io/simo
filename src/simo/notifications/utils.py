from simo.users.models import User
from .models import Notification, UserNotification


def notify_users(instance, severity, title, body=None, component=None, users=None):
    assert severity in ('info', 'warning', 'alarm')
    notification = Notification.objects.create(
        instance=instance,
        title='<strong>%s:</strong> %s' % (
            instance.name, title
        ),
        severity=severity, body=body,
        component=component
    )
    if not users:
        users = User.objects.filter(roles__instnace=instance, is_active=True)
    for user in users:
        if instance not in user.instances:
            continue
        if component and not component.can_write(user):
            continue
        UserNotification.objects.create(
            user=user, notification=notification,
        )
    notification.dispatch()
