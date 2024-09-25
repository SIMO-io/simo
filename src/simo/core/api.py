import datetime
from calendar import monthrange
import pytz
import time
import json
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.http import HttpResponse, Http404
from simo.core.utils.helpers import get_self_ip, search_queryset
from rest_framework import status
from actstream.models import Action
from rest_framework.pagination import PageNumberPagination
from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.response import Response as RESTResponse
from rest_framework.exceptions import ValidationError as APIValidationError
from simo.core.utils.config_values import ConfigException
from simo.core.utils.json import restore_json
from .models import (
    Instance, Category, Zone, Component, Icon, ComponentHistory,
    HistoryAggregate, Gateway
)
from .serializers import (
    IconSerializer, CategorySerializer, ZoneSerializer,
    ComponentSerializer, ComponentHistorySerializer,
    ActionSerializer
)
from .permissions import (
    IsInstanceSuperuser, InstanceSuperuserCanEdit, ComponentPermission
)


class InstanceMixin:

    def dispatch(self, request, *args, **kwargs):
        self.instance = Instance.objects.filter(
            slug=self.request.resolver_match.kwargs.get('instance_slug'),
            is_active=True
        ).last()
        if not self.instance:
            raise Http404()
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
            queryset = queryset.filter(
                slug__in=self.request.GET['slugs'].split(',')
            )
        if 'q' in self.request.GET:
            queryset = search_queryset(
                queryset, self.request.GET['q'], ['slug', 'keywords']
            )[:25]
        return queryset

    def get_view_name(self):
        singular = "Icon"
        plural = "Icons"
        suffix = getattr(self, 'suffix', None)
        if suffix and suffix.lower() == 'list':
            return plural
        return singular


class CategoryViewSet(InstanceMixin, viewsets.ModelViewSet):
    url = 'core/categories'
    basename = 'categories'
    serializer_class = CategorySerializer

    def get_permissions(self):
        permissions = super().get_permissions()
        permissions.append(InstanceSuperuserCanEdit())
        return permissions

    def get_queryset(self):
        return Category.objects.filter(instance=self.instance)

    def get_view_name(self):
        singular = "Category"
        plural = "Categories"
        suffix = getattr(self, 'suffix', None)
        if suffix and suffix.lower() == 'list':
            return plural
        return singular

    def perform_create(self, serializer):
        serializer.validated_data['instance'] = self.instance
        serializer.save()


class ZoneViewSet(InstanceMixin, viewsets.ModelViewSet):
    url = 'core/zones'
    basename = 'zones'
    serializer_class = ZoneSerializer

    def get_queryset(self):
        return Zone.objects.filter(instance=self.instance)

    def get_permissions(self):
        permissions = super().get_permissions()
        permissions.append(InstanceSuperuserCanEdit())
        return permissions

    def get_view_name(self):
        singular = "Zone"
        plural = "Zones"
        suffix = getattr(self, 'suffix', None)
        if suffix and suffix.lower() == 'list':
            return plural
        return singular

    def perform_create(self, serializer):
        serializer.validated_data['instance'] = self.instance
        serializer.save()

    @action(detail=False, methods=['post'])
    def reorder(self, request, pk=None, *args, **kwargs):
        data = request.data
        if not isinstance(request.data, dict):
            data = data.dict()
        request_data = restore_json(data)
        zones = {str(z.id): z for z in Zone.objects.filter(instance=self.instance)}
        if len(request_data.get('zones', [])) != len(zones):
            raise APIValidationError(
                _('All zones must be provided to perform reorder.'), code=400
            )
        for i, id in enumerate(request_data.get('zones')):
            zones[str(id)].order = i
        Zone.objects.bulk_update([z for id, z in zones.items()], fields=['order'])
        return RESTResponse({'status': 'success'})


def get_components_queryset(instance, user):
    qs = Component.objects.filter(zone__instance=instance)
    if user.is_superuser:
        return qs

    c_ids = set()

    from simo.generic.controllers import WeatherForecast

    if instance.indoor_climate_sensor:
        c_ids.add(instance.indoor_climate_sensor.id)
    wf_c = Component.objects.filter(
        zone__instance=instance,
        controller_uid=WeatherForecast.uid, config__is_main=True
    ).values('id').first()
    if wf_c:
        c_ids.add(wf_c['id'])
    main_alarm_group = Component.objects.filter(
        zone__instance=instance,
        base_type='alarm-group', config__is_main=True
    ).values('id').first()
    if main_alarm_group:
        c_ids.add(main_alarm_group['id'])

    user_role = user.get_role(instance)

    for cp in user_role.component_permissions.all():
        if cp.read:
            c_ids.add(cp.component.id)

    return qs.filter(id__in=c_ids).select_related(
        'zone', 'category', 'icon'
    ).prefetch_related('slaves')


class ComponentViewSet(
    InstanceMixin, viewsets.ModelViewSet
):
    url = 'core/components'
    basename = 'components'
    serializer_class = ComponentSerializer

    def get_permissions(self):
        permissions = super().get_permissions()
        permissions.append(ComponentPermission())
        permissions.append(InstanceSuperuserCanEdit())
        return permissions

    def get_queryset(self):
        return get_components_queryset(self.instance, self.request.user)

    def get_view_name(self):
        singular = "Component"
        plural = "Components"
        suffix = getattr(self, 'suffix', None)
        if suffix and suffix.lower() == 'list':
            return plural
        return singular

    def perform_controller_method(self, json_data, component):
        for method_name, param in json_data.items():
            if method_name in ('id', 'secret'):
                continue

            component.prepare_controller()

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
        data = request.data
        if not isinstance(request.data, dict):
            data = data.dict()
        json_data = restore_json(data)
        subcomponent_id = json_data.pop('id', -1)
        try:
            subcomponent = component.slaves.get(pk=subcomponent_id)
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
        self.check_object_permissions(self.request, subcomponent)
        return self.perform_controller_method(json_data, subcomponent)

    @action(detail=True, methods=['post'])
    def controller(self, request, pk=None, *args, **kwargs):
        start = time.time()
        component = self.get_object()
        print(f"Component retrieved in : {time.time() - start}s")
        data = request.data
        if not isinstance(request.data, dict):
            data = data.dict()
        request_data = restore_json(data)
        resp = self.perform_controller_method(request_data, component)
        print(f"Command executed in : {time.time() - start}s")
        return resp

    @action(detail=False, methods=['post'])
    def control(self, request, *args, **kwargs):
        data = request.data
        if not isinstance(request.data, dict):
            data = data.dict()
        request_data = restore_json(data)
        component = self.get_queryset().filter(id=request_data.pop('id', 0)).first()
        if not component:
            raise Http404()
        self.check_object_permissions(self.request, component)
        return self.perform_controller_method(request_data, component)

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

        if not component.controller:
            return

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


class ActionsViewset(InstanceMixin, viewsets.ReadOnlyModelViewSet):
    url = 'core/actions'
    basename = 'actions'
    serializer_class = ActionSerializer
    pagination_class = HistoryResultsSetPagination

    def get_queryset(self):
        qs = Action.objects.filter(data__instance_id=self.instance.id)
        if self.request.user.is_superuser:
            return qs
        user_role = self.request.user.get_role(self.instance)
        if user_role.is_owner:
            return qs
        Action.objects.none()


class SettingsViewSet(InstanceMixin, viewsets.GenericViewSet):
    url = 'core/settings'
    basename = 'settings'
    #http_method_names = ['get', 'head', 'options', 'patch']


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
            'hub_uid': dynamic_settings['core__hub_uid'],
            'instance_name': self.instance.name,
            'instance_uid': self.instance.uid,
            'timezone': self.instance.timezone,
            'location': self.instance.location,
            'last_event': last_event,
            'weather_forecast': wf_comp_id,
            'main_alarm_group': main_alarm_group_id,
            # TODO: Remove these two when the app is updated for everybody.
            'remote_http': dynamic_settings['core__remote_http'],
            'local_http': 'https://%s' % get_self_ip(),
            'units_of_measure': self.instance.units_of_measure,
            # editable fields
            'history_days': self.instance.history_days,
            'device_report_history_days': self.instance.device_report_history_days,
            'indoor_climate_sensor': self.instance.indoor_climate_sensor_id,
        })

    def update(self, request, *args, **kwargs):
        data = request.data
        if not isinstance(request.data, dict):
            data = data.dict()
        request_data = restore_json(data)
        if 'history_days' in request_data:
            try:
                history_days = int(request_data['history_days'])
            except:
                raise APIValidationError(
                    _('Bad value for history days!'), code=400
                )
            if history_days < 0 or history_days > 365:
                raise APIValidationError(
                    _('History days must be 0 - 365!'), code=400
                )
            self.instance.history_days = history_days
        if 'device_report_history_days' in request_data:
            try:
                device_report_history_days = int(
                    request_data['device_report_history_days']
                )
            except:
                raise APIValidationError(
                    _('Bad value for device_report_history_days days!'),
                    code=400
                )
            if device_report_history_days < 0 \
                    or device_report_history_days > 365:
                raise APIValidationError(
                    _('History days must be 0 - 365!'), code=400
                )
            self.instance.device_report_history_days = device_report_history_days

        self.instance.indoor_climate_sensor = Component.objects.filter(
            id=request_data.get('indoor_climate_sensor', 0)
        ).first()

        self.instance.save()

        return self.list(request)

    def get_serializer_class(self):
        from rest_framework.serializers import Serializer
        return Serializer

    def patch(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)


class InfoViewSet(InstanceMixin, viewsets.GenericViewSet):
    url = 'core/info'
    basename = 'info'
    # This is how you get around standard User Auth.
    authentication_classes = []
    permission_classes = []

    def list(self, request, format=None, *args, **kwargs):
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
        ).filter(zone__instance=self.instance).values(
            'id', 'value', 'last_change', 'last_modified',
            'arm_status', 'battery_level', 'alive', 'error_msg',
            'meta'
        )
        for vals in component_values:
            vals['last_change'] = datetime.datetime.timestamp(
                vals['last_change']
            )
            vals['last_modified'] = datetime.datetime.timestamp(
                vals['last_modified']
            )

        categories = Category.objects.filter(instance=self.instance).values(
            'id', 'last_modified'
        )
        for cat in categories:
            cat['last_modified'] = datetime.datetime.timestamp(
                cat['last_modified']
            )


        return RESTResponse({
            'zones': Zone.objects.filter(instance=self.instance).values(
                'id', 'name'
            ),
            'categories': categories,
            'component_values': component_values,
            'users': UserSerializer(
                users_qs, many=True, context={
                    'request': request, 'instance': self.instance
                }
            ).data
        })


class ControllerTypes(InstanceMixin, viewsets.GenericViewSet):
    url = 'core/controller-types'
    basename = 'controller-types'
    queryset = []

    def get_permissions(self):
        permissions = super().get_permissions()
        permissions.append(IsInstanceSuperuser())
        return permissions

    def list(self, request, *args, **kwargs):
        from .utils.type_constants import get_controller_types_map
        data = {}

        for uid, cls in get_controller_types_map(user=request.user).items():
            if cls.gateway_class.name not in data:
                data[cls.gateway_class.name] = []
            data[cls.gateway_class.name].append({
                'uid': uid,
                'name': cls.name,
                'is_discoverable': cls.is_discoverable,
                'manual_add': cls.manual_add,
                'discovery_msg': cls.discovery_msg,
                'info': cls.info(cls)
            })

        return RESTResponse(data)


class RunningDiscoveries(InstanceMixin, viewsets.GenericViewSet):
    url = 'core/discoveries'
    basename = 'discoveries'
    queryset = []

    def get_permissions(self):
        permissions = super().get_permissions()
        permissions.append(IsInstanceSuperuser())
        return permissions

    def get_data(self, gateways):
        data = []
        for gateway in gateways:
            gateway.discovery['last_check'] = time.time()
            gateway.save(update_fields=['discovery'])
            data.append({
                'gateway': gateway.id,
                'start': gateway.discovery['start'],
                'controller_uid': gateway.discovery['controller_uid'],
                'result': gateway.discovery['result'],
                'finished': gateway.discovery.get('finished'),
            })
        return data

    def get_gateways(self, request):
        gateways = Gateway.objects.filter(
            discovery__start__gt=time.time() - 60 * 60  # no more than an hour
        )
        if 'controller_uid' in request.GET:
            gateways = gateways.filter(
                discovery__controller_uid=request.GET['controller_uid']
            )
        return gateways

    def list(self, request, *args, **kwargs):
        return RESTResponse(self.get_data(self.get_gateways(request)))

    @action(detail=False, methods=['get', 'post'])
    def retry(self, request, *args, **kwargs):
        gateways = self.get_gateways(request)
        if 'controller_uid' in request.GET:
            for gateway in gateways:
                gateway.retry_discovery()
        return RESTResponse(self.get_data(gateways))

    @action(detail=False, methods=['get', 'post'])
    def finish(self, request, *args, **kwargs):
        gateways = self.get_gateways(request)
        if 'controller_uid' in request.GET:
            for gateway in gateways:
                gateway.finish_discovery()
        return RESTResponse(self.get_data(gateways))