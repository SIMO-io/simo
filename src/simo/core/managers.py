from django.utils import timezone
from django.db import models


class ComponentsManager(models.Manager):

    def bulk_send(self, components, value):
        from .controllers import BEFORE_SEND
        from simo.users.middleware import get_current_user
        from .events import GatewayObjectCommand

        gateway_components = {}
        for comp in components:
            v = comp.translate_before_send(value)
            v = comp.controller._validate_val(v, BEFORE_SEND)

            comp.change_init_by = get_current_user()
            comp.change_init_date = timezone.now()
            comp.save(
                update_fields=['change_init_by', 'change_init_date']
            )
            v = comp.controller._prepare_for_send(v)
            if comp.gateway not in gateway_components:
                gateway_components[comp.gateway] = []
            gateway_components[comp.gateway].append([comp.id, v])

        for gateway, send_vals in gateway_components.items():
            GatewayObjectCommand(gateway, bulk_set=send_vals).publish()