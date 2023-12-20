from rest_framework.permissions import BasePermission


class IsActivePermission(BasePermission):
    """
        Allows access only to active users.
    """

    def has_permission(self, request, view):
        return request.user.is_active
