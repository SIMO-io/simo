from rest_framework import serializers
from .models import InstanceOptions, Colonel


class InstanceOptionsSerializer(serializers.ModelSerializer):
    instance = serializers.SerializerMethodField()

    class Meta:
        model = InstanceOptions
        fields = 'instance', 'secret_key',

    def get_instance(self, obj):
        return obj.instance.uid


class ColonelSerializer(serializers.ModelSerializer):

    class Meta:
        model = Colonel
        fields = (
            'id', 'uid', 'name', 'type', 'firmware_version', 'firmware_auto_update',
            'socket_connected', 'last_seen', 'enabled', 'pwm_frequency',
            'logs_stream'
        )
        read_only_fields = [
            'uid', 'type', 'firmware_version', 'socket_connected',
            'last_seen',
        ]
