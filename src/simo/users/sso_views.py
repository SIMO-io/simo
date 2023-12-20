from urllib.parse import urlparse, urlunparse, urljoin, urlencode
from django.views.generic import View
from django.http import JsonResponse
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import authenticate, login
from django.contrib.auth.backends import ModelBackend
from itsdangerous import URLSafeTimedSerializer
from webservices.sync import SyncConsumer
from simo.conf import dynamic_settings
from django.conf import settings
from django.shortcuts import render
from simo.core.utils.helpers import get_random_string
from simo.core.utils.relay import HttpResponseRedirect

from .models import User

SSO_SERVER = 'https://simo.io/sso-server/'
SSO_PUBLIC_KEY = 'mzfUL0V4aaxvJOS8o4ahrHPVTggk9J4oNb1Hz8RAoc8jKtDMx8iUDkKR3FZsNblc'
SSO_PRIVATE_KEY = 'l1ELiixCre4SreSPQOdeER3LuQBCvJzGUEfjzSbZsXsyJ9qwVUZwMXhMjLG2yKbO'


class LoginView(View):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.consumer = SyncConsumer(
            SSO_SERVER, SSO_PUBLIC_KEY, SSO_PRIVATE_KEY
        )

    def get(self, request):
        next = self.get_next()
        scheme = 'https' if request.is_secure() \
                            or 'simo.io' in request.get_host() else 'http'
        query = urlencode([('next', next)])
        netloc = request.get_host()
        path = reverse('simple-sso-authenticate')
        redirect_to = urlunparse((scheme, netloc, path, '', query, ''))
        request_token = self.get_request_token(
            request, redirect_to
        )
        host = urljoin(SSO_SERVER, 'authorize/')
        url = '%s?%s' % (host, urlencode([('token', request_token)]))
        if request.headers.get('User-Agent', '').startswith("SIMO"):
            return JsonResponse({'url': url, 'status': 'redirect'})
        return HttpResponseRedirect(url)


    def get_next(self):
        next = self.request.GET.get('next', None)
        if not next:
            return self.request.build_absolute_uri('/admin/')
        netloc = urlparse(next)[1]
        # Don't allow redirection to a different host.
        if netloc and netloc != self.request.get_host():
            return self.request.build_absolute_uri('/admin/')
        return next


    def get_request_token(self, request, redirect_to):
        url = '/request-token/'
        if not dynamic_settings['core__hub_secret']:
            dynamic_settings['core__hub_secret'] = get_random_string(20)
        data = {
            'redirect_to': redirect_to,
            'hub_uid': dynamic_settings['core__hub_uid'],
            # 'hub_name': dynamic_settings['core__hub_name'],
            'hub_secret': dynamic_settings['core__hub_secret'],
            'access_token': request.GET.get('at', ''),
            'invitation_token': request.GET.get('invitation', '')
        }
        return self.consumer.consume(url, data)['request_token']



class AuthenticateView(LoginView):

    def get(self, request):
        raw_access_token = request.GET['access_token']
        access_token = URLSafeTimedSerializer(
            SSO_PRIVATE_KEY
        ).loads(raw_access_token)
        user_data = self.consumer.consume('/verify/', {'access_token': access_token})

        # This is a very fist time when new hub makes a connection to the master cloud
        # so we take the chance to pull down all initial configs.
        # TURNS OUT IT IS COMMING IN ON EVERY AUTHENTICATION REQUEST
        # if user_data.get('extra_data'):
        #     from simo.core.tasks import save_config
        #     save_config(user_data['extra_data'])

        user = authenticate(request, user_data=user_data)
        if not user:
            if request.headers.get('User-Agent', '').startswith("SIMO"):
                return JsonResponse({'status': 'unauthorized'}, status=403)
            msg = _("Permission denied!")
            if user_data:
                msg = _("Sorry, %s, but you are not allowed here.") % (
                    user_data['name']
                )

            return render(request, 'admin/msg_page.html', {
                'status': 'danger',
                'page_title': _("Unauthorized"),
                'msg': msg,
                'suggestion': _(
                    "Please contact somebody who manages "
                    "this instance and ask for assistance."
                )
            })


        login(request, user, backend=user.backend)
        next = self.get_next()
        if request.headers.get('User-Agent', '').startswith("SIMO"):
            return JsonResponse({'status': "success"})
        return HttpResponseRedirect(next)



