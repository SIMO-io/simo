import pytz
import datetime
import logging
import json
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


@mcp.tool(name="core.call_component_method")
async def call_component_method(
    component_id: int,
    method_name: str,
    args: list | None = None,
    kwargs: dict | None = None,
):
    """
    Calls a method on a component with given args/kwargs and returns the result if any.
    """
    def _execute():
        log.debug("Call component [%s] %s(*%s, **%s)", component_id, method_name, args, kwargs)
        current_user = get_current_user()
        if not current_user:
            introduce_user(get_ai_user())
        component = Component.objects.get(
            pk=component_id, zone__instance=get_current_instance()
        )
        fn = getattr(component, method_name)
        if args and kwargs:
            return fn(*args, **kwargs)
        if args:
            return fn(*args)
        if kwargs:
            return fn(**kwargs)
        return fn()

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