from rest_framework.permissions import BasePermission, SAFE_METHODS, IsAuthenticated
from django.http import Http404
from .middleware import introduce_instance
from .models import Instance, Category, Zone


class InstancePermission(BasePermission):
    message = "You have no role in this SIMO.io instance."

    def has_permission(self, request, view):
        if not request.user.is_active:
            return False

        instance = getattr(view, 'instance', None)
        if not instance:
            instance = Instance.objects.filter(
                slug=request.resolver_match.kwargs.get('instance_slug'),
                is_active=True
            ).first()

        if not instance:
            raise Http404()

        if instance not in request.user.instances:
            return False

        introduce_instance(instance)

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
        '''
        in this permission we only care about:
        POST - new object can be created
        PUT - create new object
        PATCH - modify an object
        DELETE - delete an oject
        '''
        # TODO: allow object creation only with PUT method, this way proper permissions system will be guaranteed.

        if request.method in SAFE_METHODS + ('POST',):
            return True

        # allow deleting only empty categories and zones
        if type(obj) in (Zone, Category) and request.method == 'DELETE'\
        and obj.components.all().count():
            return False

        if request.user.is_master:
            return True
        user_role = request.user.get_role(view.instance)
        if user_role.is_superuser:
            return True

        if user_role.is_owner and request.method != 'DELETE':
            return True

        return False


class ComponentPermission(BasePermission):
    message = "You do not have permission to do this on this component."

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.user.is_master:
            return True
        if obj.controller.masters_only:
            return False
        user_role = request.user.get_role(view.instance)
        if user_role.is_superuser:
            return True
        if user_role.is_owner and request.method != 'DELETE':
            return True
        if request.method == 'POST':
            for perm in user_role.component_permissions.all():
                if perm.component == obj:
                    return perm.write
        return False