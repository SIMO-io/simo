from rest_framework import serializers
from .models import InstanceOptions, Colonel
from .utils import get_available_gpio_pins


class InstanceOptionsSerializer(serializers.ModelSerializer):
    instance = serializers.SerializerMethodField()

    class Meta:
        model = InstanceOptions
        fields = 'instance', 'secret_key',

    def get_instance(self, obj):
        return obj.instance.uid


class ColonelSerializer(serializers.ModelSerializer):
    free_pins = serializers.SerializerMethodField()

    class Meta:
        model = Colonel
        fields = (
            'id', 'uid', 'name', 'type', 'firmware_version', 'firmware_auto_update',
            'socket_connected', 'last_seen', 'enabled', 'pwm_frequency',
            'logs_stream', 'free_pins'
        )
        read_only_fields = [
            'uid', 'type', 'firmware_version', 'socket_connected',
            'last_seen', 'free_pins'
        ]

    def get_free_pins(self, obj):
        return get_available_gpio_pins(obj)
