from django.utils import timezone
from rest_framework import viewsets, mixins
from rest_framework.decorators import action
from rest_framework.response import Response as RESTResponse
from rest_framework.pagination import PageNumberPagination
from simo.core.api import InstanceMixin
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
            qs = Notification.objects.filter(
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

