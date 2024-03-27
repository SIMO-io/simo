from rest_framework import serializers
from .models import InstanceOptions, Colonel, ColonelPin


class InstanceOptionsSerializer(serializers.ModelSerializer):
    instance = serializers.SerializerMethodField()

    class Meta:
        model = InstanceOptions
        fields = 'instance', 'secret_key',

    def get_instance(self, obj):
        return obj.instance.uid


class ColonelPinSerializer(serializers.ModelSerializer):
    occupied = serializers.SerializerMethodField()

    class Meta:
        model = ColonelPin
        fields = 'id', 'label', 'occupied'
        read_only_fields = fields

    def get_occupied(self, obj):
        return bool(obj.occupied_by)


class ColonelSerializer(serializers.ModelSerializer):
    pins = serializers.SerializerMethodField()

    class Meta:
        model = Colonel
        fields = (
            'id', 'uid', 'name', 'type', 'firmware_version', 'firmware_auto_update',
            'socket_connected', 'last_seen', 'enabled', 'pwm_frequency',
            'logs_stream', 'pins'
        )
        read_only_fields = [
            'uid', 'type', 'firmware_version', 'socket_connected',
            'last_seen', 'pins'
        ]

    def get_pins(self, obj):
        result = []
        for pin in obj.pins.all():
            result.append(ColonelPinSerializer(pin).data)
        return result

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        instance.update_config()
        return instance
