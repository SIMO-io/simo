# -*- coding: utf-8 -*-

from .utils import introduce_user, get_current_user # legacy support for older third party apps

# legacy support
introduce = introduce_user


class IntroduceUser:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            introduce_user(request.user)
        return self.get_response(request)