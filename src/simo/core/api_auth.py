from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework import HTTP_HEADER_ENCODING, exceptions
from simo.users.models import User
from simo.users.utils import introduce_user


class SecretKeyAuth(BasicAuthentication):

    def authenticate(self, request):
        secret_key = request.META.get('HTTP_SECRET')
        if secret_key:
            user = User.objects.filter(
                secret_key=secret_key
            ).first()

            if not user or not user.is_active:
                return
            introduce_user(user)
            return (user, None)

    def authenticate_header(self, request):
        return "None"


class IsAuthenticated(SessionAuthentication):

    def _should_enforce_csrf(self, request) -> bool:
        # The SIMO mobile app is not a browser and historically does not send
        # CSRF tokens with session-authenticated API requests.
        # For browser-originated requests, enforce CSRF as usual.
        try:
            meta = getattr(request, 'META', None) or request._request.META
        except Exception:
            meta = {}
        ua = (meta.get('HTTP_USER_AGENT') or '').strip()
        return not ua.startswith('SIMO')

    def authenticate(self, request):
        """
        Returns a `User` if the request session currently has a logged in user.
        Otherwise raises 401.
        """
        user = getattr(request._request, 'user', None)

        # Unauthenticated, CSRF validation not required
        if not user.is_authenticated:
            raise exceptions.NotAuthenticated()

        if self._should_enforce_csrf(request):
            self.enforce_csrf(request)

        introduce_user(user)

        return (user, None)

    def authenticate_header(self, request):
        return "None"
