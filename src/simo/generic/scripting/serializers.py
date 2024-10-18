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

    class Meta:
        model = Component
        fields = (
            'pk', 'name', 'icon', 'zone', 'category', 'base_type', 'config',
            'meta', 'value', 'value_units', 'value_previous', 'alive',
            'battery_level', 'notes', 'alarm_category', 'arm_status'
        )


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