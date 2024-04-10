# -*- coding: utf-8 -*-
import threading

# This is only ment for logging component history actions.
# Do not use this for anything permissions related!

# This technique can only be used with asgi/wsgi runners that
# are not performing thread swapping for handling simultaneous requests.
# For example gunicorn does that when configured with more than one worker,
# which eventually messes up this system.

# We use daphne for asgi, which seems to be working fine for what we have already
# observed. However, this is a good candidate for reworking it in to something
# more robust.


_thread_locals = threading.local()


def get_current_user():
    try:
        return getattr(_thread_locals, 'user')
    except:
        from .utils import get_system_user
        user = get_system_user()
        introduce(user)
        return user


def introduce(user):
    _thread_locals.user = user


class IntroduceUser:
    '''Middleware which stores user object to local threading'''

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            introduce(request.user)
        return self.get_response(request)