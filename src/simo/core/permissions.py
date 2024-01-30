from rest_framework.permissions import BasePermission, SAFE_METHODS
from .models import Instance, Category, Zone


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


class IsInstanceSuperuser(BasePermission):

    def has_permission(self, request, view):
        if request.user.is_master:
            return True
        user_role = request.user.get_role(view.instance)
        return user_role.is_superuser


class InstanceSuperuserCanEdit(BasePermission):

    def has_object_permission(self, request, view, obj):

        # allow deleting only empty categories and zones
        if type(obj) in (Zone, Category) and request.method == 'DELETE'\
        and obj.components.all().count():
            return False

        if request.user.is_master:
            return True
        user_role = request.user.get_role(view.instance)
        if user_role.is_superuser:
            return True
        return request.method in SAFE_METHODS
