from rest_framework.permissions import BasePermission, SAFE_METHODS, IsAuthenticated
from .models import Instance, Category, Zone


class InstancePermission(BasePermission):
    message = "You have no role in this SIMO.io instance."

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
    message = "Only superusers are allowed to do this."

    def has_permission(self, request, view):
        if request.user.is_master:
            return True
        user_role = request.user.get_role(view.instance)
        return user_role.is_superuser


class InstanceSuperuserCanEdit(BasePermission):
    message = "Only superusers are allowed to perform this action."

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


class ComponentPermission(BasePermission):
    message = "You do not have permission to do this on this component."

    # TODO: clean this up once the app is tested and running 100% correctly for at least 6 months.
    def has_object_permission(self, request, view, obj):
        print(f"Check permission of {request.user} on {obj}")
        if request.method in SAFE_METHODS:
            print("THIS IS SAFE METHOD!")
            return True
        if request.user.is_master:
            print("USER IS MASTER!")
            return True
        user_role = request.user.get_role(view.instance)
        if user_role.is_superuser:
            print("USER IS SUPERUSER!")
            return True
        if request.method == 'POST' and user_role.component_permissions.filter(
            write=True, component=obj
        ).count():
            print("USER HAS RIGHT TO DO THIS!")
            return True
        print("USER IS NOT ALLOWED TO DO THIS!")
        return False