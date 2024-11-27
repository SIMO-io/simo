from .serializers import *
from simo.core.models import Zone, Category, Component
from simo.users.models import InstanceUser
from simo.core.middleware import get_current_instance


def get_current_state():
    get_current_instance()
    return {
        'zones': ZoneSerializer(Zone.objects.all(), many=True).data,
        'categories': CategorySerializer(Category.objects.all(), many=True).data,
        'component': ComponentSerializer(Component.objects.all(), many=True).data,
        'instanceusers': InstanceUserSerializer(
            InstanceUser.objects.all(), many=True
        ).data,
    }