from rest_framework import serializers
from simo.core.models import Zone, Category, Component
from simo.users.models import User, InstanceUser, PermissionsRole


class ZoneSerializer(serializers.ModelSerializer):
    '''Zone serializer for AI scripts helper'''

    class Meta:
        model = Zone
        fields = 'pk', 'name'


class CategorySerializer(serializers.ModelSerializer):
    '''Category serializer for AI scripts helper'''

    class Meta:
        model = Category
        fields = 'pk', 'name'


class ComponentSerializer(serializers.ModelSerializer):
    '''Component serializer for AI scripts helper'''
    value = serializers.SerializerMethodField()
    meta = serializers.SerializerMethodField()
    config = serializers.SerializerMethodField()

    class Meta:
        model = Component
        fields = (
            'pk', 'name', 'icon', 'zone', 'category', 'base_type', 'config',
            'meta', 'value', 'value_units', 'value_previous', 'alive',
            'battery_level', 'notes', 'alarm_category', 'arm_status'
        )

    def get_value(self, obj):
        if len(str(obj.value)) > 1000:
            return str(obj.value)[:1000] + '...'
        return obj.value

    def get_meta(self, obj):
        if len(str(obj.meta)) > 1000:
            return str(obj.meta)[:1000] + '...'
        return obj.meta

    def get_config(self, obj):
        if len(str(obj.config)) > 1000:
            return str(obj.config)[:1000] + '...'
        return obj.config




class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = 'email', 'name'


class PermissionsRoleSerializer(serializers.ModelSerializer):

    class Meta:
        model = PermissionsRole
        fields = 'pk', 'name', 'is_owner', 'is_superuser'


class InstanceUserSerializer(serializers.ModelSerializer):
    '''Role serializer for AI scripts helper'''
    user = UserSerializer()
    role = PermissionsRoleSerializer()

    class Meta:
        model = InstanceUser
        fields = 'user', 'role',