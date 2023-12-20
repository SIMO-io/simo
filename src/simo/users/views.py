import re
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.urls import re_path
from django.shortcuts import get_object_or_404, render
from django.db.transaction import atomic
from django.utils import timezone
from django.urls import reverse_lazy
from django.utils.http import urlencode
from django.template.loader import render_to_string
from django.http import (
    JsonResponse, HttpResponseRedirect, HttpResponse, Http404
)
from simo.conf import dynamic_settings
from .models import InstanceInvitation


@atomic
def accept_invitation(request, token):

    invitation = get_object_or_404(InstanceInvitation, token=token)

    if invitation.expire_date < timezone.now():
        status = 'error'
        title = "Invitation expired"
        msg = render_to_string(
            'invitations/expired_msg.html', {
                'invitation': invitation,
            }
        )
        suggestion = render_to_string(
            'invitations/expired_suggestion.html', {
                'invitation': invitation,
            }
        )

    elif invitation.taken_by:
        status = 'error'
        title = "Invitation is already taken"
        msg = render_to_string(
            'invitations/taken_msg.html', {
                'invitation': invitation, 'user': request.user,
            }
        )
        suggestion = render_to_string(
            'invitations/taken_suggestion.html', {
                'invitation': invitation, 'user': request.user,
            }
        )

    else:
        if request.user.is_authenticated:
            logout(request)

        # elif request.user.is_authenticated:
        #     status = 'error'
        #     title = "You are already authenticated"
        #     msg = render_to_string(
        #         'invitations/authenticated_msg.html', {
        #             'invitation': invitation, 'user': request.user,
        #         }
        #     )
        #     suggestion = render_to_string(
        #         'invitations/authenticated_suggestion.html', {
        #             'invitation': invitation,
        #             'user': request.user,
        #         }
        #     )

        #else:

        url = '%s?%s' % (
            reverse_lazy('login'),
            urlencode([('invitation', invitation.token)])
        )
        if request.headers.get('User-Agent', '').startswith("SIMO"):
            return JsonResponse({'status': 'need-login', 'redirect': url})
        return HttpResponseRedirect(url)

    if request.headers.get('User-Agent', '').startswith("SIMO"):
        return JsonResponse({
            'status': status, 'title': title, 'msg': msg,
            'suggestion': suggestion
        })
    else:
        return render(request, 'admin/msg_page.html', {
            'status': 'danger' if status == 'error' else status, 'page_title': title,
            'msg': msg, 'suggestion': suggestion
        })

def serve_protected(request, path, prefix=''):
    if not request.user.is_authenticated:
        # Don't even let anyone know if anything exists in here
        # if not authenticated.
        raise Http404()
    response = HttpResponse(status=200)
    response['Content-Type'] = ''
    response['X-Accel-Redirect'] = '/protected' + prefix + path
    return response


def protected_static(prefix, **kwargs):
    return re_path(
        r'^%s(?P<path>.*)$' % re.escape(prefix.lstrip('/')),
        serve_protected, kwargs={'prefix': prefix}
    )
