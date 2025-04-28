from rest_framework import serializers
from simo.core.serializers import TimestampField
from .models import (
    InstanceOptions, Colonel, ColonelPin, Interface, CustomDaliDevice
)


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
        fields = 'id', 'colonel', 'no', 'type'


class ColonelSerializer(serializers.ModelSerializer):
    pins = serializers.SerializerMethodField()
    interfaces = serializers.SerializerMethodField()
    newer_firmware_available = serializers.SerializerMethodField()
    last_seen = TimestampField(read_only=True)
    is_empty = serializers.SerializerMethodField()

    class Meta:
        model = Colonel
        fields = (
            'id', 'uid', 'name', 'type',
            'firmware_version', 'firmware_auto_update',
            'newer_firmware_available',
            'socket_connected', 'last_seen', 'pins', 'interfaces',
            'is_empty'
        )
        read_only_fields = [
            'uid', 'type', 'firmware_version', 'newer_firmware_available',
            'socket_connected', 'last_seen', 'pins', 'interfaces',
            'is_empty'
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

    def get_newer_firmware_available(self, obj):
        return obj.newer_firmware_available()

    def get_is_empty(self, obj):
        return not bool(obj.components.all().count())

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        instance.update_config()
        return instance


class CustomDaliDeviceSerializer(serializers.ModelSerializer):
    is_empty = serializers.SerializerMethodField()
    is_alive = serializers.SerializerMethodField()
    last_seen = TimestampField(read_only=True)

    class Meta:
        model = CustomDaliDevice
        fields = (
            'id', 'uid', 'random_address', 'name', 'is_empty',
            'is_alive', 'last_seen'
        )
        read_only_fields = (
            'random_address', 'is_empty', 'is_alive', 'last_seen'
        )

    def validate(self, data):
        instance = self.context.get('instance')
        uid = data.get('uid')
        if instance and uid:
            if CustomDaliDevice.objects.filter(
                uid=uid, instance=instance
            ).exists():
                raise serializers.ValidationError(
                    f"A device with uid '{uid}' already exists for this instance."
                )
        return data

    def validate_uid(self, value):
        """
        Prevent changing the uid on update.
        """
        # self.instance will be None for creation, but set for updates.
        if self.instance and self.instance.uid != value:
            raise serializers.ValidationError("Changing uid is not allowed.")
        return value

    def create(self, validated_data):
        validated_data['instance'] = self.context['instance']
        return super().create(validated_data)

    def get_is_empty(self, obj):
        return not bool(obj.components.all().count())

    def get_is_alive(self, obj):
        return obj.is_alive

