import datetime
from calendar import monthrange
import pytz
import logging
from django.db.models import Q, Prefetch
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.shortcuts import get_object_or_404
from easy_thumbnails.files import get_thumbnailer
from simo.core.utils.helpers import get_self_ip
from rest_framework.pagination import PageNumberPagination
from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.response import Response as RESTResponse
from django.core.exceptions import ValidationError
from rest_framework.exceptions import ValidationError as APIValidationError
from simo.conf import dynamic_settings
from simo.core.utils.config_values import ConfigException
from .models import (
    Instance, Category, Zone, Component, Icon, ComponentHistory,
    HistoryAggregate
)
from .serializers import (
    IconSerializer, CategorySerializer, ZoneSerializer,
    ComponentSerializer, ComponentHistorySerializer
)


class InstanceMixin:

    def dispatch(self, request, *args, **kwargs):
        self.instance = Instance.objects.get(
            slug=self.request.resolver_match.kwargs.get('instance_slug')
        )
        return super().dispatch(request, *args, **kwargs)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['instance'] = self.instance
        return ctx


class IconViewSet(viewsets.ReadOnlyModelViewSet):
    url = 'core/icons'
    basename = 'icons'
    queryset = Icon.objects.all()
    serializer_class = IconSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if 'slugs' in self.request.GET:
            queryset = queryset.filter(slug__in=self.request.GET['slugs'].split(','))
        return queryset


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    url = 'core/categories'
    basename = 'categories'
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ZoneViewSet(InstanceMixin, viewsets.ReadOnlyModelViewSet):
    url = 'core/zones'
    basename = 'zones'
    serializer_class = ZoneSerializer

    def get_queryset(self):
        return Zone.objects.filter(instance=self.instance)


def get_components_queryset(instance, user):
    qs = Component.objects.filter(zone__instance=instance)
    if user.is_superuser:
        return qs

    from simo.generic.controllers import WeatherForecast
    general_components = []
    if instance.indoor_climate_sensor:
        general_components.append(instance.indoor_climate_sensor_id)
    wf_c = Component.objects.filter(
        zone__instance=instance,
        controller_uid=WeatherForecast.uid, config__is_main=True
    ).values('id').first()
    if wf_c:
        general_components.append(wf_c['id'])
    main_alarm_group = Component.objects.filter(
        zone__instance=instance,
        base_type='alarm-group', config__is_main=True
    ).values('id').first()
    if main_alarm_group:
        general_components.append(main_alarm_group['id'])

    c_ids = [
        cp.component.id for cp in
        user.get_role(instance).component_permissions.filter(
            read=True
        ).select_related('component')
    ]
    qs = qs.filter(Q(id__in=c_ids) | Q(id__in=general_components))
    return qs


class ComponentViewSet(InstanceMixin, viewsets.ReadOnlyModelViewSet):
    url = 'core/components'
    basename = 'components'
    serializer_class = ComponentSerializer

    def get_queryset(self):
        return get_components_queryset(self.instance, self.request.user).filter(
            zone__instance=self.instance
        )

    def perform_controller_method(self, json_data, component):
        for method_name, param in json_data.items():
            if not hasattr(component, method_name):
                raise APIValidationError(
                     _('"%s" method not found on controller') % method_name,
                    code=400
                )
            call = getattr(component, method_name)

            if not isinstance(param, list) and not isinstance(param, dict):
                param = [param]

            try:
                if isinstance(param, list):
                    result = call(*param)
                elif isinstance(param, dict):
                    result = call(**param)
                else:
                    result = call()
            except ConfigException as e:
                raise APIValidationError(e.data)
            except Exception as e:
                raise APIValidationError(str(e))

            return RESTResponse(result)

    @action(detail=True, methods=['post'])
    def subcomponent(self, request, pk=None, *args, **kwargs):
        component = self.get_object()
        if not request.user.is_superuser \
            and not request.get_role(self.instance).component_permissions.filter(
            write=True, component=component
        ):
            raise APIValidationError(
                _('You do not have permission to write to this component.'),
                code=403
            )
        json_data = request.data
        subcomponent_id = json_data.pop('id', -1)
        try:
            subcomponent = component.subcomponents.get(pk=subcomponent_id)
        except Component.DoesNotExist:
            raise APIValidationError(
                _('Subcomponent with id %d does not exist!' % str(subcomponent_id)),
                code=400
            )
        if not subcomponent.controller:
            raise APIValidationError(
                _('Subcomponent has no controller assigned.'),
                code=400
            )
        return self.perform_controller_method(json_data, subcomponent)


    def check_object_permissions(self, request, component):
        super().check_object_permissions(request, component)
        if not request.user.is_superuser\
        and not request.user.get_role(self.instance).component_permissions.filter(
            write=True, component=component
        ):
            raise APIValidationError(
                _('You do not have permission to write to this component.'),
                code=403
            )
        if not component.controller:
            raise APIValidationError(
                _('Component has no controller assigned.'),
                code=400
            )

    @action(detail=True, methods=['post'])
    def controller(self, request, pk=None, *args, **kwargs):
        component = self.get_object()
        return self.perform_controller_method(request.data, component)

    @action(detail=False, methods=['post'])
    def control(self, request, *args, **kwargs):
        component = get_object_or_404(Component, id=request.data.pop('id', 0))
        self.check_object_permissions(self.request, component)
        return self.perform_controller_method(request.data, component)

    @action(detail=True, methods=['get'])
    def value_history(self, request, pk=None, *args, **kwargs):
        component = self.get_object()
        resp_data = {
            'metadata': component.controller._get_value_history_chart_metadata(),
            'entries': component.controller._get_value_history(
                period=self.request.GET.get('period', 'day')
            )
        }
        return RESTResponse(resp_data)


class HistoryResultsSetPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100


class ComponentHistoryViewSet(InstanceMixin, viewsets.ReadOnlyModelViewSet):
    url = 'core/component_history'
    basename = 'component_history'
    serializer_class = ComponentHistorySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['component', 'type']
    pagination_class = HistoryResultsSetPagination

    def get_queryset(self):
        qs = ComponentHistory.objects.filter(
            component__zone__instance=self.instance,
        )
        if self.request.user.is_superuser:
            return qs
        c_ids = [
            cp.component.id for cp in
            self.request.user.get_role(self.instance).component_permissions.filter(
                read=True
            ).select_related('component')
        ]
        qs = qs.filter(component__id__in=c_ids)
        return qs

    def list(self, request, format=None, *args, **kwargs):
        if request.GET.get('interval', None) in ('min', 'hour', 'day', 'week', 'month') \
        and 'component' in request.GET and 'start_from' in request.GET:
            component = Component.objects.get(pk=request.GET['component'])
            start_from = datetime.datetime.utcfromtimestamp(
                int(float(request.GET['start_from']))
            ).replace(tzinfo=pytz.utc)

            start_from = start_from.astimezone(
                pytz.timezone(self.instance.timezone)
            )

            if request.GET['interval'] == 'min':
                start_from = start_from - datetime.timedelta(
                    seconds=start_from.second
                )
            if request.GET['interval'] == 'hour':
                start_from = start_from - datetime.timedelta(
                    minutes=start_from.minute, seconds=start_from.second
                )
            if request.GET['interval'] in ('day', 'week'):
                start_from = start_from - datetime.timedelta(
                    hours=start_from.hour,
                    minutes=start_from.minute, seconds=start_from.second
                )
            if request.GET['interval'] == 'month':
                if start_from.day > 1:
                    days_to_to_detract = start_from.day - 1
                else:
                    days_to_to_detract = 0
                start_from = start_from - datetime.timedelta(
                    days=days_to_to_detract, hours=start_from.hour,
                    minutes=start_from.minute, seconds=start_from.second
                )

            print("START FROM: ", start_from)

            return RESTResponse(
                self.get_aggregated_data(
                    component, request.GET['interval'], start_from
                ),
            )
        return super().list(request, format)

    def get_aggregated_data(self, component, interval, start_from):

        history_display_example = component.controller.history_display([component.value])
        if not history_display_example:
            return None

        def get_aggregated_history_value(prev_val, start, end):

            if end < timezone.now():
                try:
                    return HistoryAggregate.objects.filter(
                        component=component, type='value', start=start, end=end
                    ).first().value
                except:
                    pass

            if start < timezone.now():
                history_items = ComponentHistory.objects.filter(
                    component=component, date__gt=start, date__lte=end,
                    type='value'
                )
                val = None
                if history_items:
                    values = []
                    for item in history_items:
                        values.append(item.value)
                    val = component.controller.history_display(values)
            else:
                val = component.controller.history_display([])

            if not val:
                val = prev_val

            if end < timezone.now():
                try:
                    HistoryAggregate.objects.create(
                        component=component, type='value',
                        start=start, end=end,
                        value=val
                    )
                except:
                    pass

            return val

        vectors = []
        for i in range(len(history_display_example)):
            vector = {
                'name': history_display_example[i]['name'],
                'type': history_display_example[i]['type'],
                'labels': [], 'data': []
            }
            vectors.append(vector)

        last_event = ComponentHistory.objects.filter(
            component=component, date__lt=start_from, type='value'
        ).order_by('date').last()
        if last_event:
            prev_val = component.controller.history_display([last_event.value])
        else:
            prev_val = history_display_example

        if interval == 'min':
            for s in range(0, 62, 2):
                start = start_from - datetime.timedelta(seconds=1) + datetime.timedelta(seconds=s)
                end = start_from + datetime.timedelta(seconds=1) + datetime.timedelta(seconds=s)
                history_val = get_aggregated_history_value(prev_val, start, end)
                prev_val = history_val
                for i, vector in enumerate(vectors):
                    vector['labels'].append(s)
                    vector['data'].append(history_val[i]['val'])

        elif interval == 'hour':
            for min in range(0, 62, 2):
                start = start_from - datetime.timedelta(minutes=1) + datetime.timedelta(minutes=min)
                end = start_from + datetime.timedelta(minutes=1) + datetime.timedelta(minutes=min)

                history_val = get_aggregated_history_value(prev_val, start, end)
                prev_val = history_val
                for i, vector in enumerate(vectors):
                    vector['labels'].append(min)
                    vector['data'].append(history_val[i]['val'])

        elif interval == 'day':
            for h in range(25):
                start = start_from - datetime.timedelta(minutes=30) + datetime.timedelta(hours=h)
                end = start_from + datetime.timedelta(minutes=30) + datetime.timedelta(hours=h)

                history_val = get_aggregated_history_value(prev_val, start, end)
                prev_val = history_val
                for i, vector in enumerate(vectors):
                    vector['labels'].append(h)
                    vector['data'].append(history_val[i]['val'])

        elif interval == 'week':
            week_map = {1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI', 7: 'VII'}
            for h in range(29):
                start = start_from - datetime.timedelta(hours=3) + datetime.timedelta(hours=h*6)
                end = start_from + datetime.timedelta(hours=3) + datetime.timedelta(hours=h*6)

                history_val = get_aggregated_history_value(prev_val, start, end)
                prev_val = history_val
                for i, vector in enumerate(vectors):
                    vector['labels'].append(week_map.get((start + datetime.timedelta(hours=3)).isoweekday(), 'X'))
                    vector['data'].append(history_val[i]['val'])

        elif interval == 'month':
            current = start_from
            xday, no_of_days = monthrange(start_from.year, start_from.month)
            for day in range(no_of_days + 1):
                start = start_from - datetime.timedelta(hours=12) + datetime.timedelta(days=day)
                end = start_from + datetime.timedelta(hours=12) + datetime.timedelta(days=day)

                history_val = get_aggregated_history_value(prev_val, start, end)
                prev_val = history_val
                for i, vector in enumerate(vectors):
                    vector['labels'].append(current.day)
                    if current < timezone.now():
                        vector['data'].append(history_val[i]['val'])
                    else:
                        vector['data'].append(None)

                current += datetime.timedelta(days=1)

        return vectors


class SettingsViewSet(InstanceMixin, viewsets.GenericViewSet):
    url = 'core/settings'
    basename = 'settings'

    def list(self, request, format=None, *args, **kwargs):
        from simo.conf import dynamic_settings

        last_event = None
        last_history_event = ComponentHistory.objects.filter(
            component__zone__instance=self.instance
        ).order_by('-date').first()
        if last_history_event:
            last_event = last_history_event.date.timestamp()

        from simo.generic.controllers import WeatherForecast

        wf_comp_id = None
        wf_c = Component.objects.filter(
            zone__instance=self.instance,
            controller_uid=WeatherForecast.uid, config__is_main=True
        ).first()
        if wf_c:
            wf_comp_id = wf_c.id

        main_alarm_group_id = None
        main_alarm_group = Component.objects.filter(
            zone__instance=self.instance,
            base_type='alarm-group', config__is_main=True
        ).first()
        if main_alarm_group:
            main_alarm_group_id = main_alarm_group.id

        return RESTResponse({
            'instance_name': self.instance.name,
            'instance_uid': self.instance.uid,
            'timezone': self.instance.timezone,
            'location': self.instance.location,
            'last_event': last_event,
            'indoor_climate_sensor': self.instance.indoor_climate_sensor_id,
            'weather_forecast': wf_comp_id,
            'main_alarm_group': main_alarm_group_id,
            'remote_http': dynamic_settings['core__remote_http'],
            'local_http': 'https://%s' % get_self_ip(),
            'units_of_measure': self.instance.units_of_measure
        })


class InfoViewSet(InstanceMixin, viewsets.GenericViewSet):
    url = 'core/info'
    basename = 'info'
    # This is how you get around standard User Auth.
    authentication_classes = []
    permission_classes = []

    def list(self, request, format=None, *args, **kwargs):
        from simo.conf import dynamic_settings
        resp = RESTResponse({'uid': self.instance.uid})
        resp["Access-Control-Allow-Origin"] = "*"
        return resp


class StatesViewSet(InstanceMixin, viewsets.GenericViewSet):
    url = 'core/states'
    basename = 'states'

    def list(self, request, format=None, *args, **kwargs):
        from simo.users.models import User
        from simo.users.serializers import UserSerializer
        users_qs = User.objects.filter(
            instance_roles__instance=self.instance
        ).order_by(
            '-last_action'
        ).exclude(email__in=('system@simo.io', 'device@simo.io'))
        component_values = get_components_queryset(
            self.instance, request.user
        ).filter(zone__instance=self.instance).prefetch_related(
            Prefetch('history', queryset=ComponentHistory.objects.filter())
        ).values(
            'id', 'value', 'last_change', 'arm_status', 'battery_level',
            'alive', 'meta'
        )
        for vals in component_values:
            vals['last_change'] = datetime.datetime.timestamp(
                vals['last_change']
            )

        return RESTResponse({
            'component_values': component_values,
            'users': UserSerializer(
                users_qs, many=True, context={
                    'request': request, 'instance': self.instance
                }
            ).data
        })
