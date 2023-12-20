# -*- coding: utf-8 -*-
import threading

_thread_locals = threading.local()


def get_current_user():
    #TODO: VERY BAD PRACTICE!!! DROP THIS!
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
        response = self.get_response(request)
        if request.user.is_authenticated:
            introduce(request.user)
        return response

