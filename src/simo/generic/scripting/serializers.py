from rest_framework import serializers
from simo.core.models import Zone, Category, Component
from simo.users.models import User, InstanceUser, PermissionsRole


class ZoneSerializer(serializers.ModelSerializer):
    '''Zone serializer for AI scripts helper'''

    class Meta:
        model = Zone
        fields = 'id', 'name'


class CategorySerializer(serializers.ModelSerializer):
    '''Category serializer for AI scripts helper'''

    class Meta:
        model = Category
        fields = 'id', 'name'


class ComponentSerializer(serializers.ModelSerializer):
    '''Component serializer for AI scripts helper'''

    MAX_LENGTH = 500

    value = serializers.SerializerMethodField()
    meta = serializers.SerializerMethodField()
    config = serializers.SerializerMethodField()

    class Meta:
        model = Component
        fields = (
            'id', 'name', 'icon', 'zone', 'category', 'base_type',
            'value', 'value_units', 'meta', 'config'
        )

    def get_value(self, obj):
        if obj.base_type in ('ip-camera', ):
            return 'SKIP'
        if len(str(obj.value)) > self.MAX_LENGTH:
            return 'SKIP'
        return obj.value

    def get_meta(self, obj):
        if len(str(obj.value)) > self.MAX_LENGTH:
            return 'SKIP'
        return obj.value

    def get_config(self, obj):
        if len(str(obj.value)) > self.MAX_LENGTH:
            return 'SKIP'
        return obj.value


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = 'email', 'name'


class PermissionsRoleSerializer(serializers.ModelSerializer):

    class Meta:
        model = PermissionsRole
        fields = 'id', 'name', 'is_owner', 'is_superuser'


class InstanceUserSerializer(serializers.ModelSerializer):
    '''Role serializer for AI scripts helper'''
    user = UserSerializer()
    role = PermissionsRoleSerializer()

    class Meta:
        model = InstanceUser
        fields = 'user', 'role',