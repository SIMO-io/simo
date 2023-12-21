from rest_framework import serializers
from collections.abc import Iterable
from simo.core.middleware import get_current_request
from simo.core.serializers import TimestampField
from easy_thumbnails.files import get_thumbnailer
from .models import User, PermissionsRole, InstanceInvitation, InstanceUser


class UserSerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField()
    role = serializers.IntegerField(source='role_id')
    at_home = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if isinstance(self.instance, Iterable):
            for inst in self.instance:
                inst.set_instance(self.context['instance'])
        elif self.instance:
            self.instance.set_instance(self.context['instance'])

    class Meta:
        model = User
        fields = (
            'id', 'email', 'name', 'avatar', 'role', 'is_active',
            'at_home', 'last_action'
        )
        read_only_fields = (
            'id', 'email', 'name', 'avatar', 'at_home', 'last_action', 'ssh_key'
        )

    def get_avatar(self, obj):
        if obj.avatar:
            url = obj.avatar['avatar'].url
            request = get_current_request()
            if request:
                url = request.build_absolute_uri(url)
            return {
                'url': url,
                'last_change': obj.avatar_last_change.timestamp()
            }
        return None

    def get_at_home(self, obj):
        return InstanceUser.objects.filter(
            user=obj
        ).first().at_home



class PermissionsRoleSerializer(serializers.ModelSerializer):

    class Meta:
        model = PermissionsRole
        fields = '__all__'


class InstanceInvitationSerializer(serializers.ModelSerializer):

    class Meta:
        model = InstanceInvitation
        fields = '__all__'
        read_only_fields = (
            'instance', 'token', 'from_user', 'taken_by',
        )
