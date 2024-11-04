import requests
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import models
from django.utils import timezone
from simo.users.models import User
from simo.core.models import Instance, Component
from simo.conf import dynamic_settings


class Notification(models.Model):
    instance = models.ForeignKey(
        Instance, on_delete=models.CASCADE, limit_choices_to={'is_active': True}
    )
    datetime = models.DateTimeField(auto_now_add=True)
    to_users = models.ManyToManyField(
        User, through='notifications.UserNotification'
    )
    severity = models.CharField(
        max_length=100, choices=(
            ('info', _("Info")), ('warning', _("Warning")),
            ('alarm', _("Alarm"))
        ), db_index=True
    )
    title = models.CharField(max_length=500)
    body = models.TextField(null=True, blank=True)
    component = models.ForeignKey(
        Component, null=True, blank=True, on_delete=models.SET_NULL
    )

    def dispatch(self):
        data = {
            'instance_uid': self.instance.uid,
            'hub_secret': dynamic_settings['core__hub_secret'],
            'notification_id': self.id, 'severity': self.severity,
            'title': self.title, 'body': self.body,
            'to_tokens': []
        }
        if self.component:
            data['component_id'] = self.component.id
        user_notifications = self.user_notifications.filter(sent__isnull=True)
        for user_notification in user_notifications:
            token = user_notification.user.primary_device_token
            if token:
                data['to_tokens'].append(
                    user_notification.user.primary_device_token
                )
        try:
            response = requests.post(
                'https://simo.io/api/notifications/postmaster/', json=data
            )
        except:
            return
        if response.json().get('status') == 'success':
            user_notifications.update(sent=timezone.now())


class UserNotification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name='user_notifications'
    )
    sent = models.DateTimeField(null=True, blank=True, db_index=True)
    archived = models.DateTimeField(null=True, blank=True, db_index=True)

