import json
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework import HTTP_HEADER_ENCODING, exceptions
from simo.users.models import User


class SecretKeyAuth(BasicAuthentication):

    def authenticate(self, request):
        secret_key = request.META.get('HTTP_SECRET')
        if secret_key:
            user = User.objects.filter(
                secret_key=secret_key
            ).first()

            if not user or not user.is_active:
                return

            return (user, None)

    def authenticate_header(self, request):
        return "None"


class IsAuthenticated(SessionAuthentication):

    def authenticate(self, request):
        """
        Returns a `User` if the request session currently has a logged in user.
        Otherwise raises 401.
        """
        user = getattr(request._request, 'user', None)

        # Unauthenticated, CSRF validation not required
        if not user.is_authenticated:
            raise exceptions.NotAuthenticated()

        return (user, None)

    def authenticate_header(self, request):
        return "None"




