import os
import io
import requests
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Exists, OuterRef, Q
from django.contrib.auth.backends import ModelBackend
from .models import User, InstanceInvitation, InstanceUser



class SIMOUserBackend(ModelBackend):

    def with_perm(self, perm, is_active=True, include_superusers=True, obj=None):
        """
        Return users that have permission "perm". By default, filter out
        inactive users and include superusers.
        """
        if isinstance(perm, str):
            try:
                app_label, codename = perm.split('.')
            except ValueError:
                raise ValueError(
                    'Permission name should be in the form '
                    'app_label.permission_codename.'
                )
        elif not isinstance(perm, Permission):
            raise TypeError(
                'The `perm` argument must be a string or a permission instance.'
            )

        UserModel = get_user_model()
        if obj is not None:
            return UserModel._default_manager.none()

        permission_q = Q(group__user=OuterRef('pk')) | Q(user=OuterRef('pk'))
        if isinstance(perm, Permission):
            permission_q &= Q(pk=perm.pk)
        else:
            permission_q &= Q(codename=codename, content_type__app_label=app_label)

        user_q = Exists(Permission.objects.filter(permission_q))
        if include_superusers:
            user_q |= Q(is_superuser=True)
        if is_active is not None:
            user_q &= Q(instance_roles__is_active=is_active).distinct()

        return UserModel._default_manager.filter(user_q)


# TODO: get explanation when user tries to log in to admin but is unable to, because of lack of permissions on his role
# TODO: allow for additional checkups if somebody would like to implement

class SSOBackend(ModelBackend):

    @transaction.atomic
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
            InstanceUser.objects.update_or_create(
                user=user, instance=invitation.instance,
                defaults={'role': invitation.role}
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
