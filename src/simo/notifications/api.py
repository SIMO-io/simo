from django.utils import timezone
from rest_framework import viewsets, mixins
from rest_framework.decorators import action
from rest_framework.response import Response as RESTResponse
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from simo.core.api import InstanceMixin
from simo.core.models import Component
from simo.users.models import InstanceUser
from simo.notifications.utils import notify_users
from .models import Notification, UserNotification
from .serializers import NotificationSerializer


class NotificationsPaginator(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class NotificationsViewSet(
        mixins.DestroyModelMixin,
        InstanceMixin,
        viewsets.ReadOnlyModelViewSet
    ):
    url = 'notifications'
    basename = 'notifications'
    serializer_class = NotificationSerializer
    pagination_class = NotificationsPaginator

    def get_queryset(self):
        qs = Notification.objects.filter(
            instance=self.instance,
            user_notifications__user=self.request.user,
        )
        if 'archived' in self.request.query_params:
            try:
                archived = bool(int(self.request.query_params['archived']))
            except:
                archived = False
            qs = qs.filter(
                user_notifications__archived__isnull=not archived,
                user_notifications__user=self.request.user
            )
        return qs.distinct().order_by('-datetime')

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None, *args, **kwargs):
        notification = self.get_object()
        UserNotification.objects.filter(
            notification=notification, user=self.request.user,
            archived__isnull=True
        ).update(archived=timezone.now())
        return RESTResponse({'status': 'success'})

    @action(detail=False, methods=['post'], url_path='send')
    def send(self, request, *args, **kwargs):
        """Send a notification to one or more instance users.

        Used by simo-sdk via `POST /api/<instance>/notifications/send/`.
        """

        if not request.user.is_master:
            role = request.user.get_role(self.instance)
            if not role or not (role.is_superuser or role.is_owner):
                raise PermissionDenied()

        severity = (request.data.get('severity') or '').strip().lower()
        if severity not in ('info', 'warning', 'alarm'):
            raise ValidationError('Invalid severity')

        title = (request.data.get('title') or '').strip()
        if not title:
            raise ValidationError('title is required')

        body = request.data.get('body')
        component_id = request.data.get('component_id')
        instance_user_ids = request.data.get('instance_user_ids')

        component = None
        if component_id is not None:
            try:
                component_id_int = int(component_id)
            except Exception:
                raise ValidationError('Invalid component_id')
            component = Component.objects.filter(
                id=component_id_int,
                zone__instance=self.instance,
            ).first()
            if component_id_int and not component:
                raise ValidationError('component not found')

        instance_users = None
        if instance_user_ids is not None:
            ids: list[int] = []
            if isinstance(instance_user_ids, list):
                for x in instance_user_ids:
                    try:
                        ids.append(int(x))
                    except Exception:
                        continue
            instance_users = InstanceUser.objects.filter(
                instance=self.instance,
                is_active=True,
                id__in=ids,
            ).select_related('user')

        notify_users(
            severity=severity,
            title=title,
            body=body,
            component=component,
            instance_users=instance_users,
            instance=self.instance,
        )
        return RESTResponse({'status': 'success'})
