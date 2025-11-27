import pytz
import datetime
import logging
import json
from concurrent.futures import ThreadPoolExecutor
from asgiref.sync import sync_to_async
from django.utils import timezone
from simo.mcp_server.app import mcp
from fastmcp.tools.tool import ToolResult
from simo.users.utils import get_current_user, introduce_user, get_ai_user
from simo.core.middleware import get_current_instance
from .models import Zone, Component, ComponentHistory
from .serializers import MCPBasicZoneSerializer, MCPFullComponentSerializer
from .utils.type_constants import BASE_TYPE_CLASS_MAP

log = logging.getLogger(__name__)


@mcp.tool(name="core.get_state")
async def get_state() -> dict:
    """
    PRIMARY RESOURCE – returns full current system state.
    """
    def _build():
        inst = get_current_instance()
        data = {
            "unix_timestamp": int(timezone.now().timestamp()),
            "ai_memory": inst.ai_memory,
            "zones": MCPBasicZoneSerializer(
                Zone.objects.filter(instance=inst).prefetch_related(
                    "components", "components__category",
                    "components__gateway", "components__slaves"
                ),
                many=True,
            ).data,
            "component_base_types": {},
        }
        for slug, cls in BASE_TYPE_CLASS_MAP.items():
            data["component_base_types"][slug] = {
                "name": str(cls.name),
                "description": str(cls.description),
                "purpose": str(cls.purpose),
                "basic_methods": str(cls.required_methods),
            }
        return data

    return await sync_to_async(_build, thread_sensitive=True)()


@mcp.tool(name="core.get_component")
async def get_component(id: str) -> dict:
    """
    Returns full component state, configs, metadata, methods, values, etc.
    """
    def _load(component_id: str):
        component = (
            Component.objects.filter(pk=component_id, zone__instance=get_current_instance())
            .select_related("zone", "category", "gateway")
            .first()
        )
        return MCPFullComponentSerializer(component).data

    return await sync_to_async(_load, thread_sensitive=True)(id)


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
    def _load(_start: int, _end: int, _ids: str):
        inst = get_current_instance()
        tz = pytz.timezone(inst.timezone)
        qs = (
            ComponentHistory.objects.filter(
                component__zone__instance=inst,
                date__gt=datetime.datetime.fromtimestamp(int(_start), tz=timezone.utc),
                date__lt=datetime.datetime.fromtimestamp(int(_end), tz=timezone.utc),
            )
            .select_related("user")
            .order_by("-date")
        )
        if _ids != "-":
            ids = [int(c_id) for c_id in _ids.split("-")]
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

    return await sync_to_async(_load, thread_sensitive=True)(start, end, component_ids)


@mcp.tool(name="core.execute_component_methods")
async def execute_component_methods(
    operations: list
):
    """
    Execute many component method calls in parallel and return their outputs
    in the original order.

    ``operations`` must be a list where every element is either
    ``[component_id, method_name]`` or
    ``[component_id, method_name, args, kwargs]``. ``args`` must be a list (or
    ``None``) and ``kwargs`` a dict (or ``None``). The tool fans out the calls
    concurrently so long-running components do not block others. Example:

    ``operations`` may use positional lists/tuples or keyword dictionaries.
    Valid formats:

    - ``[component_id, method_name]``
    - ``[component_id, method_name, args, kwargs]``
    - ``{"component_id": 101, "method_name": "turn_on", "args": [], "kwargs": {}}``

    ``args`` must be a list (or ``None``) and ``kwargs`` a dict (or ``None``).
    The tool fans out the calls concurrently so long-running components do not
    block others. Example: ``[[101, "turn_on"], [202, "set_level", [75], None]]``

    Always expect the response list to align positionally with the operations
    you supplied. This makes it easy for AI orchestrators to fan out work and
    then correlate each reply without additional bookkeeping.
    """
    def _execute():
        log.debug(f"Execute component methods: {operations}")
        current_user = get_current_user()
        if not current_user:
            introduce_user(get_ai_user())

        instance = get_current_instance()

        if not operations:
            return []

        def _normalize(op):
            if isinstance(op, dict):
                component_id = op.get('component_id') or op.get('id')
                method_name = op.get('method_name') or op.get('method')
                args = op.get('args')
                kwargs = op.get('kwargs')
            else:
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
    def _execute(text):
        inst = get_current_instance()
        inst.ai_memory = text
        inst.save(update_fields=['ai_memory'])

    return await sync_to_async(_execute, thread_sensitive=True)(text)


@mcp.tool(name="core.get_unix_timestamp")
async def get_unix_timestamp() -> int:
    """
    Get current unix timestamp epoch seconds
    """
    return int(timezone.now().timestamp())
