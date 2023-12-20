from rest_framework.permissions import BasePermission
from .models import Instance


class InstancePermission(BasePermission):
    """
       Allows access only to user instances
    """

    def has_permission(self, request, view):
        if not request.user.is_active:
            return False

        instance = Instance.objects.filter(
            slug=request.resolver_match.kwargs.get('instance_slug')
        ).first()
        if not instance:
            return False

        if instance not in request.user.instances:
            return False

        return True
