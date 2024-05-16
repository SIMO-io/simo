from rest_framework import serializers
from .models import InstanceOptions, Colonel, ColonelPin, Interface


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
        try:
            return bool(obj.occupied_by)
        except AttributeError:
            # apparently the item type that this pin was occupied by
            # was deleted from the codebase, so we quickly fix it here. :)
            obj.occupied_by = None
            obj.save()
            return False


class ColonelInterfaceSerializer(serializers.ModelSerializer):

    class Meta:
        model = Interface
        fields = 'id', 'no', 'type'
        read_only_fields = fields


class ColonelSerializer(serializers.ModelSerializer):
    pins = serializers.SerializerMethodField()
    interfaces = serializers.SerializerMethodField()

    class Meta:
        model = Colonel
        fields = (
            'id', 'uid', 'name', 'type', 'firmware_version', 'firmware_auto_update',
            'socket_connected', 'last_seen', 'enabled', 'pwm_frequency',
            'logs_stream', 'pins', 'interfaces',
        )
        read_only_fields = [
            'uid', 'type', 'firmware_version', 'socket_connected',
            'last_seen', 'pins', 'interfaces',
        ]

    def get_pins(self, obj):
        result = []
        for pin in obj.pins.all():
            result.append(ColonelPinSerializer(pin).data)
        return result

    def get_interfaces(self, obj):
        result = []
        for interface in obj.interfaces.all():
            result.append(ColonelInterfaceSerializer(interface).data)
        return result

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        instance.update_config()
        return instance
