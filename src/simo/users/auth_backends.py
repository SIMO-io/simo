import os
import io
import requests
from django.core.files import File
from django.contrib.auth.backends import ModelBackend
from django.utils import timezone
from .models import User, InstanceInvitation, InstanceUser


# TODO: get explanation when user tries to log in to admin but is unable to, because of lack of permissions on his role
# TODO: allow for additional checkups if somebody would like to implement

class SSOBackend(ModelBackend):

    def authenticate(self, request, user_data=None, **kwargs):
        system_user_emails = ('system@simo.io', 'device@simo.io')
        if not user_data:
            return
        if user_data['email'] in system_user_emails: # not valid email address.
            return

        user = None
        try:
            user = User.objects.get(email=user_data['email'])
        except User.DoesNotExist:
            # There is no real user on a hub yet, except System
            # so we create first user right away!
            if not User.objects.all().exclude(email__in=system_user_emails).count():
                user = User.objects.create(
                    email=user_data['email'],
                    name=user_data['name'],
                    is_master=True,
                )

        try:
            invitation = InstanceInvitation.objects.get(
                token=user_data.get('invitation_token'),
                taken_by__isnull=True, expire_date__gt=timezone.now()
            )
        except InstanceInvitation.DoesNotExist:
            invitation = None
        else:
            if not user:
                user = User.objects.create(
                    email=user_data['email'], name=user_data['name']
                )

        if not user:
            return

        if invitation:
            invitation.taken_by = user
            invitation.save()
            InstanceUser.objects.create(
                user=user, role=invitation.role,
                instance=invitation.instance
            )

        if user_data.get('name'):
            user.name = user_data['name']
        if user_data.get('avatar_url') \
        and user.avatar_url != user_data.get('avatar_url'):
            user.avatar_url = user_data.get('avatar_url')
            resp = requests.get(user.avatar_url)
            user.avatar.save(
                os.path.basename(user.avatar_url), io.BytesIO(resp.content)
            )
        user.save()

        if user.is_active:
            return user
