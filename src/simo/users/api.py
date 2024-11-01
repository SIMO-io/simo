import sys
import datetime
from django.db.models import Q
from rest_framework import viewsets, mixins, status
from rest_framework.serializers import Serializer
from rest_framework.decorators import action
from rest_framework.response import Response as RESTResponse
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.contrib.gis.geos import Point
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from simo.conf import dynamic_settings
from simo.core.api import InstanceMixin
from .models import (
    User, UserDevice, UserDeviceReportLog, PermissionsRole, InstanceInvitation,
    Fingerprint, ComponentPermission, InstanceUser
)
from .serializers import (
    UserSerializer, PermissionsRoleSerializer, InstanceInvitationSerializer,
    FingerprintSerializer, ComponentPermissionSerializer
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

        return queryset.filter(
            Q(roles__instance=self.instance) | Q(id=self.request.user.id)
        ).distinct()


    def check_permission_to_change(self, request, target_user):
        user_role = request.user.get_role(self.instance)
        if request.user.is_master:
            return user_role
        if user_role.is_superuser:
            return user_role
        if user_role.can_manage_users:
            return user_role
        msg = 'You are not allowed to change this!'
        print(msg, file=sys.stderr)
        raise ValidationError(msg, code=403)


    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        target_user = self.get_object()
        user_role = self.check_permission_to_change(request, target_user)

        for key, val in request.data.items():
            if key not in ('role', 'is_active'):
                request.data.pop(key)


        serializer = self.get_serializer(
            target_user, data=request.data, partial=partial
        )
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            print(e, file=sys.stderr)
            raise ValidationError(str(e), code=403)

        try:
            set_role_to = PermissionsRole.objects.get(
                pk=request.data.get('role')
            )
        except:
            pass
        else:
            if set_role_to != target_user.get_role(self.instance) \
            and set_role_to.is_superuser \
            and not user_role.is_superuser:
                msg = "You are not allowed to grant superuser roles to others " \
                      "if you are not a superuser yourself."
                print(msg, file=sys.stderr)
                raise ValidationError(msg, code=403)

            if target_user == request.user \
            and user_role and user_role.is_superuser \
            and not set_role_to.is_superuser:
            # User is trying to downgrade his own role from
            # superuser to something lower, we must make sure
            # there is at least one user left that has superuser role on this instance.
                if not User.objects.filter(
                    roles__instance=self.instance, roles__is_superuser=True
                ).exclude(id=target_user.id).values('id').first():
                    msg = "You are the only one superuser on this instance, " \
                          "therefore you are not alowed to downgrade your role."
                    print(msg, file=sys.stderr)
                    raise ValidationError(msg, code=403)

        self.perform_update(serializer)

        if getattr(target_user, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            target_user._prefetched_objects_cache = {}

        return RESTResponse(serializer.data)

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if request.user.pk == user.pk:
            raise ValidationError(
                'Deleting yourself is not allowed!', code=403
            )
        if request.user.is_superuser:
            pass
        else:
            role = request.user.get_role(self.instance)
            if not role or not role.can_manage_users:
                raise ValidationError(
                    'You do not have permission for this!', code=403
                )
        self.perform_destroy(user)
        return RESTResponse(status=status.HTTP_204_NO_CONTENT)


class RolesViewsets(InstanceMixin, viewsets.ReadOnlyModelViewSet):
    url = 'users/roles'
    basename = 'roles'
    serializer_class = PermissionsRoleSerializer

    def get_queryset(self):
        return PermissionsRole.objects.filter(instance=self.instance)


class ComponentPermissionViewsets(
    InstanceMixin,
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
    mixins.ListModelMixin, viewsets.GenericViewSet
):
    url = 'users/componentpermissions'
    basename = 'componentpermissions'
    serializer_class = ComponentPermissionSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['component', 'role']

    def get_queryset(self):
        return ComponentPermission.objects.filter(role__instance=self.instance)

    def update(self, request, *args, **kwargs):
        if request.user.is_master:
            return super().update(request, *args, **kwargs)
        iuser = InstanceUser.objects.get(
            instance=self.instance, user=request.user
        ).select_related('role')
        if not iuser.is_active:
            raise PermissionDenied()
        if iuser.role.is_owner or iuser.role.is_superuser:
            return super().update(request, *args, **kwargs)
        raise PermissionDenied()


class UserDeviceReport(InstanceMixin, viewsets.GenericViewSet):
    url = 'users'
    basename = 'device_report'
    serializer_class = Serializer

    @action(url_path='device-report', detail=False, methods=['post'])
    def report(self, request, *args, **kwargs):
        from simo.generic.scripting.helpers import haversine_distance
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

        defaults = {'os': request.data['os']}
        user_device, new = UserDevice.objects.get_or_create(
            token=request.data['device_token'],
            defaults=defaults
        )
        user_device.users.add(request.user)

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


        user_device.last_seen = timezone.now()
        if location:
            user_device.last_seen_location = ','.join(
                [str(i) for i in location]
            ) if location else None

        if request.data.get('app_open', False):
            user_device.is_primary = True
            UserDevice.objects.filter(
                users=request.user
            ).exclude(id=user_device.id).update(is_primary=False)
        user_device.save()

        speed_kmh = request.data.get('speed', 0) * 3.6
        for iu in request.user.instance_roles.filter(is_active=True):
            if location:
                iu.at_home = haversine_distance(
                    iu.instance.location, user_device.last_seen_location
                ) < dynamic_settings['users__at_home_radius']
            elif not relay:
                iu.at_home = True

            iu.last_seen = user_device.last_seen
            iu.last_seen_location = user_device.last_seen_location
            iu.last_seen_speed_kmh = speed_kmh
            iu.phone_on_charge = request.data.get('is_charging', False)
            iu.save()

        UserDeviceReportLog.objects.create(
            user_device=user_device, instance=self.instance,
            app_open=request.data.get('app_open', False),
            location=','.join([str(i) for i in location]) if location else None,
            relay=relay, speed_kmh=speed_kmh,
            phone_on_charge=request.data.get('is_charging', False)
        )

        return RESTResponse({'status': 'success'})


class InvitationsViewSet(InstanceMixin, viewsets.ModelViewSet):
    url = 'users/invitations'
    basename = 'invitations'
    serializer_class = InstanceInvitationSerializer

    def get_queryset(self):
        if not self.request.user.is_superuser:
            role = self.request.user.get_role(self.instance)
            if not role or not role.can_manage_users:
                return InstanceInvitation.objects.none()
        return InstanceInvitation.objects.filter(instance=self.instance)

    def create(self, request, *args, **kwargs):
        role = PermissionsRole.objects.filter(
            instance=self.instance, is_default=True
        ).first()
        if not role:
            role = PermissionsRole.objects.filter(
                instance=self.instance
            ).first()
        if role:
            request.data['role'] = role.id
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(instance=self.instance, from_user=self.request.user)
        headers = self.get_success_headers(serializer.data)
        return RESTResponse(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
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


class FingerprintViewSet(
    InstanceMixin,
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
    mixins.DestroyModelMixin, mixins.ListModelMixin,
    viewsets.GenericViewSet
):
    url = 'users/fingerprints'
    basename = 'fingerprints'
    serializer_class = FingerprintSerializer

    def get_queryset(self):
        qs = Fingerprint.objects.filter(
            Q(user=None) | Q(user__roles__instance=self.instance)
        )
        if 'values' in self.request.GET:
            qs = qs.filter(value__in=self.request.GET['values'].split(','))
        return qs

    def check_can_manage_user(self, request):
        user_role = request.user.get_role(self.instance)
        if not request.user.is_superuser:
            if not user_role or not user_role.can_manage_users:
                msg = 'You are not allowed to change this!'
                print(msg, file=sys.stderr)
                raise ValidationError(msg, code=403)

    def update(self, request, *args, **kwargs):
        self.check_can_manage_user(request)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self.check_can_manage_user(request)
        return super().destroy(request, *args, **kwargs)

