from rest_framework import serializers
from collections.abc import Iterable
from simo.core.middleware import get_current_request, get_current_instance
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
        return obj.is_active

    def get_avatar(self, obj):
        if not obj.avatar:
            return
        try:
            url = obj.avatar['avatar'].url
        except:
            return
        request = get_current_request()
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
