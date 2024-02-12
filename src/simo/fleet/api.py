from django.db.models import Count
from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as APIValidationError
from simo.core.api import InstanceMixin
from simo.core.permissions import IsInstanceSuperuser
from .models import InstanceOptions, Colonel
from .serializers import InstanceOptionsSerializer, ColonelSerializer


class InstanceOptionsViewSet(InstanceMixin, viewsets.ReadOnlyModelViewSet):
    url = 'fleet/options'
    basename = 'options'
    serializer_class = InstanceOptionsSerializer

    def get_queryset(self):
        return InstanceOptions.objects.filter(instance=self.instance)


class ColonelsViewSet(InstanceMixin, viewsets.ModelViewSet):
    url = 'fleet/colonels'
    basename = 'colonels'
    serializer_class = ColonelSerializer

    def get_permissions(self):
        permissions = super().get_permissions()
        permissions.append(IsInstanceSuperuser())
        return permissions

    def get_queryset(self):
        return Colonel.objects.filter(instance=self.instance)

    @action(detail=True, methods=['post'])
    def check_for_upgrade(self, request, pk=None, *args, **kwargs):
        colonel = self.get_object()
        colonel.check_for_upgrade()

    @action(detail=True, methods=['post'])
    def upgrade(self, request, pk=None, *args, **kwargs):
        colonel = self.get_object()
        if colonel.major_upgrade_available:
            colonel.update_firmware(colonel.major_upgrade_available)
        elif colonel.minor_upgrade_available:
            colonel.update_firmware(colonel.minor_upgrade_available)

    @action(detail=True, methods=['post'])
    def restart(self, request, pk=None, *args, **kwargs):
        colonel = self.get_object()
        colonel.restart()

    @action(detail=True, methods=['post'])
    def update_config(self, request, pk=None, *args, **kwargs):
        colonel = self.get_object()
        colonel.update_config()


    @action(detail=True, methods=['post'])
    def move_to(self, request, pk, *args, **kwargs):
        colonel = self.get_object()
        target = Colonel.objects.annotate(
            components_count=Count('components')
        ).filter(
            pk=request.POST.get('target'),
            components_count=0, type=colonel.type
        )
        if not target:
            raise APIValidationError(_('Invalid target.'), code=400)
        colonel.move_to(target)
