from rest_framework import serializers
from collections.abc import Iterable
from simo.core.middleware import get_current_instance
from simo.core.utils.api import ReadWriteSerializerMethodField
from .models import (
    User, PermissionsRole, ComponentPermission,
    InstanceInvitation, InstanceUser, Fingerprint
)


class UserSerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField()
    role = serializers.IntegerField(source='role_id')
    at_home = serializers.SerializerMethodField()
    is_active = ReadWriteSerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = User
        fields = (
            'id', 'email', 'name', 'avatar', 'role', 'is_master', 'is_active',
            'at_home', 'last_action'
        )
        read_only_fields = (
            'id', 'email', 'name', 'avatar', 'at_home', 'last_action', 'ssh_key',
            'is_master'
        )

    def get_is_active(self, obj):
        iu = InstanceUser.objects.filter(
            user=obj, instance=get_current_instance()
        ).first()
        try:
            return iu.is_active
        except:
            return False

    def get_avatar(self, obj):
        if not obj.avatar:
            return
        try:
            url = obj.avatar['avatar'].url
        except:
            return
        request = self.context['request']
        if request:
            url = request.build_absolute_uri(url)
        return {
            'url': url,
            'last_change': obj.avatar_last_change.timestamp()
        }

    def get_at_home(self, obj):
        iu = InstanceUser.objects.filter(
            user=obj, instance=get_current_instance()
        ).first()
        if iu:
            return iu.at_home
        return False



class PermissionsRoleSerializer(serializers.ModelSerializer):

    class Meta:
        model = PermissionsRole
        fields = '__all__'


class ComponentPermissionSerializer(serializers.ModelSerializer):

    class Meta:
        model = ComponentPermission
        fields = '__all__'


class InstanceInvitationSerializer(serializers.ModelSerializer):

    class Meta:
        model = InstanceInvitation
        fields = '__all__'
        read_only_fields = (
            'instance', 'token', 'from_user', 'taken_by',
        )


class FingerprintSerializer(serializers.ModelSerializer):
    type = serializers.SerializerMethodField()

    class Meta:
        model = Fingerprint
        fields = 'id', 'type', 'value', 'user', 'name'
        read_only_fields = ('id', 'type', 'value')

    def get_type(self, obj):
        return obj.type


class InstanceUserSDKSerializer(serializers.ModelSerializer):
    """InstanceUser representation for simo-sdk."""

    user_id = serializers.IntegerField(source='user.id', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    name = serializers.CharField(source='user.name', read_only=True)

    role_id = serializers.IntegerField(source='role.id', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    role_is_owner = serializers.BooleanField(source='role.is_owner', read_only=True)
    role_is_superuser = serializers.BooleanField(source='role.is_superuser', read_only=True)
    role_can_manage_users = serializers.BooleanField(source='role.can_manage_users', read_only=True)
    role_is_person = serializers.BooleanField(source='role.is_person', read_only=True)

    last_seen = serializers.SerializerMethodField()

    class Meta:
        model = InstanceUser
        fields = (
            'id',
            'user_id', 'email', 'name',
            'role_id', 'role_name',
            'role_is_owner', 'role_is_superuser',
            'role_can_manage_users', 'role_is_person',
            'is_active',
            'at_home',
            'last_seen',
            'last_seen_location',
            'last_seen_speed_kmh',
            'phone_on_charge',
        )

    def get_last_seen(self, obj):
        if obj.last_seen:
            return obj.last_seen.timestamp()
        return None
