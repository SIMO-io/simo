from functools import wraps

from django.middleware.csrf import CsrfViewMiddleware
from django.views.decorators.csrf import csrf_exempt


def simo_csrf_exempt(view_func):
    """CSRF-exempt for SIMO app, enforced for browsers.

    The SIMO mobile app uses session-authenticated requests without CSRF tokens.
    Browser-originated requests should still be protected against CSRF.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        ua = ''
        try:
            ua = request.headers.get('User-Agent', '') or ''
        except Exception:
            try:
                ua = request.META.get('HTTP_USER_AGENT', '') or ''
            except Exception:
                ua = ''

        if not ua.startswith('SIMO'):
            middleware = CsrfViewMiddleware(lambda req: None)
            response = middleware.process_view(request, view_func, args, kwargs)
            if response is not None:
                return response

        return view_func(request, *args, **kwargs)

    return csrf_exempt(_wrapped)

