from simo.core.serializers import TimestampField
from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    datetime = TimestampField()

    class Meta:
        model = Notification
        fields = (
            'id', 'datetime', 'severity', 'title', 'body',
            'component', 'to_users'
        )

    def __init__(self, *args, **kwargs):
        self._user = kwargs['context']['request'].user
        super().__init__(*args, **kwargs)
