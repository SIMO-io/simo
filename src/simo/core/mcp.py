import pytz
import datetime
import inspect
import logging
from typing import Any, TypeAlias

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from concurrent.futures import ThreadPoolExecutor
from asgiref.sync import sync_to_async
from django.db import close_old_connections
from django.utils import timezone
from simo.mcp_server.app import mcp
from simo.users.utils import get_current_user, introduce_user, get_ai_user
from simo.core.middleware import get_current_instance, introduce_instance
from simo.core.throttling import check_throttle, SimpleRequest
from .models import Zone, Component, ComponentHistory

log = logging.getLogger(__name__)


class ExecuteComponentMethodOperation(BaseModel):
    model_config = ConfigDict(extra='ignore', populate_by_name=True)

    component_id: int = Field(
        ...,
        description=(
            "Numeric component ID (database primary key). "
            "Always use the numeric `id` returned by `core.query_components`."
        ),
        validation_alias=AliasChoices('component_id', 'id'),
    )
    method_name: str = Field(
        ...,
        description="Controller method name to execute (e.g. `turn_off`).",
        validation_alias=AliasChoices('method_name', 'method'),
    )
    args: list[Any] | None = Field(
        default=None,
        description="Positional arguments for the method (or null).",
    )
    kwargs: dict[str, Any] | None = Field(
        default=None,
        description="Keyword arguments for the method (or null).",
    )


ExecuteComponentMethodOp2: TypeAlias = tuple[int, str]
ExecuteComponentMethodOp3: TypeAlias = tuple[int, str, list[Any] | None]
ExecuteComponentMethodOp4: TypeAlias = tuple[int, str, list[Any] | None, dict[str, Any] | None]
ExecuteComponentMethodOp: TypeAlias = (
    ExecuteComponentMethodOperation
    | ExecuteComponentMethodOp2
    | ExecuteComponentMethodOp3
    | ExecuteComponentMethodOp4
)


class QueryComponentsRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')

    zone_ids: list[int] | None = Field(
        default=None,
        description="Filter by zone ids.",
    )
    base_types: list[str] | None = Field(
        default=None,
        description="Filter by component base types.",
    )
    category_names: list[str] | None = Field(
        default=None,
        description="Filter by exact component category names.",
    )
    alive: bool | None = Field(
        default=None,
        description="Filter by current alive state.",
    )


def _clean_list(values):
    if not values:
        return []
    out = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        out.append(value)
    return out


def _method_description(method) -> str | None:
    doc = inspect.getdoc(method) or ''
    if not doc:
        return None
    return doc.strip().splitlines()[0].strip() or None


def _get_action_value_contract(component, method_name: str) -> dict | None:
    base_type = component.base_type
    config = component.config or {}

    if method_name == 'output_percent':
        return {
            'type': 'number',
            'min': 0,
            'max': 100,
        }

    if method_name == 'pulse':
        return {
            'type': 'object',
            'properties': {
                'frame_length_s': {'type': 'number', 'exclusive_minimum': 0},
                'on_percentage': {'type': 'number', 'min': 0, 'max': 100},
            },
            'required': ['frame_length_s', 'on_percentage'],
        }

    if method_name != 'send':
        return None

    if base_type == 'state-select':
        return {
            'type': 'string',
            'allowed_values': [
                state.get('slug')
                for state in config.get('states', [])
                if isinstance(state, dict) and state.get('slug')
            ],
        }

    if base_type == 'switch':
        return {'type': 'boolean'}

    if base_type in ('double-switch', 'triple-switch', 'quadruple-switch', 'quintuple-switch'):
        current_value = component.value if isinstance(component.value, list) else []
        channel_count = len(current_value) or {
            'double-switch': 2,
            'triple-switch': 3,
            'quadruple-switch': 4,
            'quintuple-switch': 5,
        }.get(base_type, 0)
        return {
            'type': 'one_of',
            'variants': [
                {'type': 'boolean'},
                {
                    'type': 'array',
                    'items': {'type': 'boolean'},
                    'length': channel_count,
                },
            ],
        }

    if base_type == 'lock':
        return {'type': 'boolean'}

    if base_type == 'dimmer':
        return {
            'type': 'number',
            'min': config.get('min', 0.0),
            'max': config.get('max', 100.0),
        }

    if base_type == 'dimmer-plus':
        return {
            'type': 'object',
            'properties': {
                'main': {
                    'type': 'number',
                    'min': config.get('main_min', 0.0),
                    'max': config.get('main_max', 1.0),
                },
                'secondary': {
                    'type': 'number',
                    'min': config.get('secondary_min', 0.0),
                    'max': config.get('secondary_max', 1.0),
                },
            },
            'required': [],
        }

    if base_type == 'rgbw-light':
        scene_format = '#rrggbbww' if config.get('has_white') else '#rrggbb'
        return {
            'type': 'object',
            'properties': {
                'scenes': {
                    'type': 'array',
                    'length': 5,
                    'items': {
                        'type': 'string',
                        'format': scene_format,
                    },
                },
                'active': {
                    'type': 'integer',
                    'min': 0,
                    'max': 4,
                },
                'is_on': {'type': 'boolean'},
            },
            'required': ['active', 'is_on'],
        }

    if base_type == 'blinds':
        open_duration_ms = int((config.get('open_duration') or 0) * 1000)
        return {
            'type': 'object',
            'properties': {
                'target': {
                    'type': 'integer',
                    'allowed_values': [-1],
                    'min': 0,
                    'max': open_duration_ms,
                    'description': '-1 means stop immediately.',
                },
                'angle': {
                    'type': 'integer',
                    'min': 0,
                    'max': 180,
                    'required': False,
                },
            },
            'required': ['target'],
        }

    if base_type == 'gate':
        if config.get('action_method') == 'click':
            allowed_values = ['call']
        else:
            allowed_values = ['open', 'close', 'call']
        return {
            'type': 'string',
            'allowed_values': allowed_values,
        }

    return None


def _build_action_contract(component, method_name: str, method) -> dict:
    action = {
        'method_name': method_name,
    }
    description = _method_description(method)
    if description:
        action['description'] = description

    signature = inspect.signature(method)
    parameters = list(signature.parameters.values())
    if not parameters:
        action['args'] = []
        return action

    if len(parameters) == 1:
        parameter = parameters[0]
        arg_schema = {
            'name': parameter.name,
        }
        value_contract = _get_action_value_contract(component, method_name)
        if value_contract:
            arg_schema.update(value_contract)
        else:
            arg_schema['type'] = 'unknown'
        if parameter.default is not inspect._empty:
            arg_schema['default'] = parameter.default
            arg_schema['required'] = False
        else:
            arg_schema['required'] = True
        action['args'] = [arg_schema]
        return action

    args = []
    for parameter in parameters:
        arg = {
            'name': parameter.name,
            'type': 'unknown',
            'required': parameter.default is inspect._empty,
        }
        if parameter.default is not inspect._empty:
            arg['default'] = parameter.default
        args.append(arg)
    action['args'] = args
    action['signature'] = str(signature)
    return action


def _build_component_actions(component) -> list[dict]:
    component.prepare_controller()
    controller = component.controller
    if not controller:
        return []

    actions = []
    for method_name, method in inspect.getmembers(controller, predicate=inspect.ismethod):
        if method_name.startswith('_'):
            continue
        if method_name in ('info', 'set'):
            continue
        if method_name == 'send' and not getattr(controller, 'accepts_value', True):
            continue
        actions.append(_build_action_contract(component, method_name, method))

    if component.alarm_category:
        for extra in ('arm', 'disarm'):
            method = getattr(component, extra, None)
            if method and callable(method) and extra not in {a['method_name'] for a in actions}:
                actions.append(_build_action_contract(component, extra, method))

    return sorted(actions, key=lambda item: item['method_name'])


def _build_query_component_summary(component) -> dict:
    return {
        'id': component.id,
        'name': component.name,
        'zone_id': component.zone_id,
        'zone_name': component.zone.name,
        'base_type': component.base_type,
        'category_name': component.category.name if component.category_id else None,
        'alive': component.alive,
        'value': component.value,
        'value_units': component.value_units,
        'breach_delay': component.breach_delay,
        'actions': _build_component_actions(component),
    }


def _build_main_component_summary(component) -> dict:
    return {
        'id': component.id,
        'name': component.name,
        'zone_id': component.zone_id,
        'zone_name': component.zone.name,
        'base_type': component.base_type,
        'value': component.value,
        'alive': component.alive,
        'breach_delay': component.breach_delay,
    }


def _build_weather_summary(component) -> dict:
    value = component.value if isinstance(component.value, dict) else {}
    weather_items = value.get('weather') or []
    first_weather = weather_items[0] if isinstance(weather_items, list) and weather_items else {}
    main = value.get('main') if isinstance(value.get('main'), dict) else {}
    wind = value.get('wind') if isinstance(value.get('wind'), dict) else {}
    return {
        'component_id': component.id,
        'name': component.name,
        'zone_id': component.zone_id,
        'zone_name': component.zone.name,
        'summary': first_weather.get('description'),
        'temperature': main.get('temp'),
        'feels_like': main.get('feels_like'),
        'wind_speed': wind.get('speed'),
        'alive': component.alive,
    }


def _format_component_map_item(component) -> str:
    icon_slug = component.icon.slug if component.icon_id and component.icon else ''
    return f"#{component.id}|{icon_slug}|{component.name}"


def _build_zone_overview(zone) -> dict:
    component_map = {}
    components = list(zone.components.all())

    for component in components:
        component_map.setdefault(component.base_type, []).append(
            _format_component_map_item(component)
        )

    return {
        'id': zone.id,
        'name': zone.name,
        'components': component_map,
    }

@mcp.tool(name="core.get_home_overview")
async def get_home_overview() -> dict:
    """
    Compact house overview for voice assistant orientation.
    """
    inst = get_current_instance()
    if not inst:
        raise PermissionError('No instance context')

    def _build(current_instance):
        close_old_connections()
        try:
            introduce_instance(current_instance)
        except Exception:
            pass

        from simo.generic.controllers import Weather

        zones = list(
            Zone.objects.filter(instance=current_instance)
            .prefetch_related('components', 'components__icon')
            .order_by('order', 'id')
        )

        weather_component = (
            Component.objects.filter(
                zone__instance=current_instance,
                controller_uid=Weather.uid,
                config__is_main=True,
            )
            .select_related('zone')
            .first()
        )
        main_house_state = (
            Component.objects.filter(
                zone__instance=current_instance,
                base_type='state-select',
                config__is_main=True,
            )
            .select_related('zone')
            .first()
        )

        tz = pytz.timezone(current_instance.timezone)
        now = timezone.localtime(timezone.now(), tz)

        return {
            'unix_timestamp': int(now.timestamp()),
            'timezone': current_instance.timezone,
            'local_time': now.strftime('%Y-%m-%d %H:%M:%S'),
            'units_of_measure': current_instance.units_of_measure,
            'ai_memory': current_instance.ai_memory,
            'weather': _build_weather_summary(weather_component) if weather_component else None,
            'main_house_state': _build_main_component_summary(main_house_state) if main_house_state else None,
            'component_map_item_format': '#component_id|icon_slug|component_name',
            'zones': [_build_zone_overview(zone) for zone in zones],
        }

    return await sync_to_async(_build, thread_sensitive=True)(inst)

@mcp.tool(name="core.query_components")
async def query_components(
    zone_ids: list[int] | None = None,
    base_types: list[str] | None = None,
    category_names: list[str] | None = None,
    alive: bool | None = None,
) -> dict:
    """
    Query components by structured filters and return compact actionable summaries.
    """
    inst = get_current_instance()
    if not inst:
        raise PermissionError('No instance context')

    request = QueryComponentsRequest(
        zone_ids=zone_ids,
        base_types=base_types,
        category_names=category_names,
        alive=alive,
    )

    def _load(current_instance):
        close_old_connections()
        try:
            introduce_instance(current_instance)
        except Exception:
            pass

        cleaned_zone_ids = _clean_list(request.zone_ids)
        cleaned_base_types = _clean_list(request.base_types)
        cleaned_category_names = _clean_list(request.category_names)

        if not cleaned_zone_ids and not cleaned_base_types and not cleaned_category_names:
            raise ValueError(
                'At least one of zone_ids, base_types or category_names must be provided.'
            )

        qs = Component.objects.filter(zone__instance=current_instance).select_related(
            'zone', 'category', 'gateway'
        ).order_by('zone__order', 'zone__id', 'id')

        if cleaned_zone_ids:
            qs = qs.filter(zone_id__in=cleaned_zone_ids)
        if cleaned_base_types:
            qs = qs.filter(base_type__in=cleaned_base_types)
        if cleaned_category_names:
            qs = qs.filter(category__name__in=cleaned_category_names)
        if request.alive is not None:
            qs = qs.filter(alive=request.alive)

        components = list(qs)
        return {
            'component_count': len(components),
            'components': [_build_query_component_summary(component) for component in components],
        }

    return await sync_to_async(_load, thread_sensitive=True)(inst)


@mcp.tool(name="core.get_component_value_change_history")
async def get_component_value_change_history(
    start: int, end: int, component_ids: str
) -> list:
    """
    Returns up to 100 component value change history records.

    - start: unix epoch seconds (older than)
    - end:   unix epoch seconds (younger than)
    - component_ids: ids joined by '-' OR '-' to include all
    """
    inst = get_current_instance()
    if not inst:
        raise PermissionError('No instance context')

    def _load(_start: int, _end: int, _ids: str, current_instance):
        close_old_connections()
        try:
            introduce_instance(current_instance)
        except Exception:
            pass

        tz = pytz.timezone(current_instance.timezone)
        qs = (
            ComponentHistory.objects.filter(
                component__zone__instance=current_instance,
                date__gt=datetime.datetime.fromtimestamp(int(_start), tz=timezone.utc),
                date__lt=datetime.datetime.fromtimestamp(int(_end), tz=timezone.utc),
            )
            .select_related("user")
            .order_by("-date")
        )
        if _ids != "-":
            ids = []
            for raw_id in _ids.split("-"):
                try:
                    ids.append(int(raw_id))
                except Exception:
                    continue
            if not ids:
                return []
            qs = qs.filter(component__id__in=ids)
        history = []
        for item in qs[:100]:
            history.append({
                "component_id": item.component.id,
                "datetime": timezone.localtime(item.date, tz).strftime("%Y-%m-%d %H:%M:%S"),
                "type": item.type,
                "value": item.value,
                "alive": item.alive,
                "user": item.user.name if item.user_id else None,
            })
        return history

    return await sync_to_async(_load, thread_sensitive=True)(start, end, component_ids, inst)


@mcp.tool(name="core.execute_component_methods")
async def execute_component_methods(
    operations: list[ExecuteComponentMethodOp]
):
    """
    Execute many component method calls in parallel and return their outputs
    in the original order.

    ``operations`` must be a list, each element describing a single component
    method call. Component identifiers MUST be numeric component IDs returned
    by `core.query_components`.

    Supported operation formats:

    - ``{"component_id": 101, "method_name": "turn_on"}``
    - ``{"component_id": 101, "method_name": "send", "args": [75]}``
    - ``[101, "turn_on"]``
    - ``[202, "send", [75], null]``

    Always expect the response list to align positionally with the operations
    you supplied. This makes it easy for AI orchestrators to fan out work and
    then correlate each reply without additional bookkeeping.
    """
    def _execute():
        close_old_connections()
        log.debug(f"Execute component methods: {operations}")
        current_user = get_current_user()
        if not current_user:
            introduce_user(get_ai_user())

        wait = check_throttle(
            request=SimpleRequest(user=get_current_user()),
            scope='mcp.execute',
        )
        if wait > 0:
            raise PermissionError('Throttled')

        instance = get_current_instance()

        if not operations:
            return []

        def _normalize(op):
            if isinstance(op, ExecuteComponentMethodOperation):
                return op.component_id, op.method_name, op.args, op.kwargs
            if isinstance(op, dict):
                component_id = op.get('component_id') or op.get('id')
                method_name = op.get('method_name') or op.get('method')
                args = op.get('args')
                kwargs = op.get('kwargs')
                return component_id, method_name, args, kwargs

            # Array/tuple form: [component_id, method_name, args?, kwargs?]
            component_id = op[0]
            method_name = op[1]
            args = op[2] if len(op) > 2 else None
            kwargs = op[3] if len(op) > 3 else None
            return component_id, method_name, args, kwargs

        def _run(op):
            component_id, method_name, args, kwargs = _normalize(op)
            component = Component.objects.get(
                pk=component_id, zone__instance=instance
            )

            # Ensure tenant/user context is available inside worker threads.
            try:
                introduce_instance(instance)
            except Exception:
                pass
            try:
                introduce_user(current_user)
            except Exception:
                pass

            component.prepare_controller()
            if not component.controller:
                raise PermissionError('Component has no controller')
            allowed_methods = set(component.get_controller_methods())
            if method_name not in allowed_methods:
                raise PermissionError(f'Method {method_name} not allowed')

            fn = getattr(component, method_name)
            has_args = args is not None
            has_kwargs = kwargs is not None
            if not has_args and not has_kwargs:
                return fn()
            if not has_args:
                args = []
            if not has_kwargs:
                kwargs = {}
            return fn(*args, **kwargs)

        max_workers = max(1, min(len(operations), 8))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(_run, operations))
        return results

    return await sync_to_async(_execute, thread_sensitive=True)()


@mcp.tool(name="core.update_ai_memory")
async def update_ai_memory(text):
    """
    Overrides ai_memory with new memory text
    """
    inst = get_current_instance()
    if not inst:
        raise PermissionError('No instance context')

    def _execute(text, current_instance):
        close_old_connections()
        try:
            introduce_instance(current_instance)
        except Exception:
            pass
        current_instance.ai_memory = text
        current_instance.save(update_fields=['ai_memory'])

    return await sync_to_async(_execute, thread_sensitive=True)(text, inst)


@mcp.tool(name="core.get_unix_timestamp")
async def get_unix_timestamp() -> int:
    """
    Get current unix timestamp epoch seconds
    """
    return int(timezone.now().timestamp())
