from rest_framework import viewsets, mixins, status
from rest_framework.serializers import Serializer
from rest_framework.decorators import action
from rest_framework.response import Response as RESTResponse
from rest_framework.exceptions import ValidationError
from django.contrib.gis.geos import Point
from simo.core.api import InstanceMixin
from .models import (
    User, UserDevice, UserDeviceReportLog, PermissionsRole, InstanceInvitation,
)
from .serializers import (
    UserSerializer, PermissionsRoleSerializer, InstanceInvitationSerializer
)


class UsersViewSet(mixins.RetrieveModelMixin,
                   mixins.UpdateModelMixin,
                   mixins.DestroyModelMixin,
                   mixins.ListModelMixin,
                   InstanceMixin,
                   viewsets.GenericViewSet):
    url = 'users/users'
    basename = 'users'
    serializer_class = UserSerializer

    def get_queryset(self):
        queryset = User.objects.all().order_by(
            '-last_action'
        ).exclude(
            email__in=('system@simo.io', 'device@simo.io')
        ) # Exclude system user

        return queryset.filter(roles__instance=self.instance)


    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)

        for key, val in request.data.items():
            if key not in ('role', 'is_active'):
                request.data.pop(key)

        user = self.get_object()
        user.set_instance(self.instance)
        if request.user.is_superuser \
        or request.user.get_role(self.instance).can_manage_users:
            pass
        else:
            raise ValidationError(
                'You are not allowed to change this!',
                code=403
            )

        serializer = self.get_serializer(
            user, data=request.data, partial=partial
        )
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            raise ValidationError(str(e), code=403)

        try:
            set_role_to = PermissionsRole.objects.get(id=request.data.get('role'))
        except Exception as e:
            raise ValidationError(e, code=403)

        if set_role_to.is_superuser:
            if request.user.is_superuser \
            or request.user.get_role(self.instance).is_superuser:
                pass
            else:
                raise ValidationError(
                    "You are not allowed to grant superuser roles to others "
                    "if you are not a superuser yourself.",
                    code=403
                )

        if user == request.user \
        and request.user.get_role(self.instance).is_superuser \
        and not set_role_to.is_superuser:
        # User is trying to downgrade his own role from
        # superuser to something lower, we must make sure
        # there is at least one user left that has superuser role on this instance.
            if not User.objects.filter(
                roles__instance=self.instance, roles__is_superuser=True
            ).exclude(id=user.id).values('id').first():
                raise ValidationError(
                    "You are the only one superuser on this instance, "
                    "therefore you are not alowed to downgrade your role.",
                    code=403
                )

        self.perform_update(serializer)

        if getattr(user, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            user._prefetched_objects_cache = {}

        return RESTResponse(serializer.data)

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if request.user.is_superuser \
        or request.user.get_role(self.instance).is_superuser:
            pass
        elif request.user.pk == user.pk:
            pass
        else:
            raise ValidationError(
                'You do not have permission for this!', code=403
            )
        self.perform_destroy(user)
        return RESTResponse(status=status.HTTP_204_NO_CONTENT)


class RolesViewsets(InstanceMixin, viewsets.ReadOnlyModelViewSet):
    url = 'users/roles'
    basename = 'roles'
    serializer_class = PermissionsRoleSerializer
    queryset = PermissionsRole.objects.all()

    def get_queryset(self):
        return PermissionsRole.objects.filter(instance=self.instance)


class UserDeviceReport(viewsets.GenericViewSet):
    url = 'users'
    basename = 'device_report'
    serializer_class = Serializer

    @action(url_path='device-report', detail=False, methods=['post'])
    def report(self, request, *args, **kwargs):

        if not request.data.get('device_token'):
            return RESTResponse(
                {'status': 'error', 'msg': 'device_token - not provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not request.data.get('os'):
            return RESTResponse(
                {'status': 'error', 'msg': 'os - not provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        defaults = {'os': request.data['os'], 'user': request.user}
        user_device, new = UserDevice.objects.get_or_create(
            token=request.data['device_token'],
            defaults=defaults
        )
        if not new:
            for key, val in defaults.items():
                setattr(user_device, key, val)
            user_device.save()
        try:
            location = Point(
                *[float(c) for c in request.data.get('location').split(',')],
                srid=4326
            )
        except:
            location = None

        relay = None
        if request.META.get('HTTP_HOST', '').endswith('.simo.io'):
            relay = request.META.get('HTTP_HOST')

        log_entry = UserDeviceReportLog.objects.create(
            user_device=user_device,
            app_open=request.data.get('app_open', False),
            location=','.join([str(i) for i in location]) if location else None,
            relay=relay
        )
        # Do not keep more than 1000 entries for every device.
        for log in UserDeviceReportLog.objects.filter(
            user_device=user_device
        )[1000:]:
            log.delete()

        user_device.last_seen = log_entry.datetime
        if log_entry.location:
            user_device.last_seen_location = log_entry.location
        if log_entry.app_open:
            user_device.is_primary = True
        user_device.save()

        return RESTResponse({'status': 'success'})


class InvitationsViewSet(InstanceMixin, viewsets.ModelViewSet):
    url = 'users/invitations'
    basename = 'invitations'
    serializer_class = InstanceInvitationSerializer

    def get_queryset(self):
        if self.request.user.is_superuser \
        or self.request.user.get_role(self.instance).can_manage_users:
            return InstanceInvitation.objects.filter(instance=self.instance)
        return InstanceInvitation.objects.none()

    def perform_create(self, serializer):
        serializer.save(
            from_user=self.request.user, instance=self.instance
        )

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None, *args, **kwargs):
        invitation = self.get_object()
        response = invitation.send()
        if not response or response.status_code != 200:
            return RESTResponse(
                {'status': 'error',
                 'msg': 'Something went wrong.'},
                status=400
            )
        return RESTResponse(response.json())