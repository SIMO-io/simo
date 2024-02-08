from django.utils import timezone
from django.db import models


class ComponentsManager(models.Manager):

    def bulk_send(self, data):
        """
        :param data: {component1: True, component2: False, component3: 55.0}
        :return:
        """
        from .models import Component
        from .controllers import BEFORE_SEND
        from simo.users.middleware import get_current_user
        from .events import GatewayObjectCommand

        for component, value in data.items():
            assert isinstance(component, Component), \
                "Component: value map is required!"

        gateway_components = {}
        for comp, value in data.items():
            value = comp.translate_before_send(value)
            value = comp.controller._validate_val(value, BEFORE_SEND)

            comp.change_init_by = get_current_user()
            comp.change_init_date = timezone.now()
            comp.save(
                update_fields=['change_init_by', 'change_init_date']
            )
            value = comp.controller._prepare_for_send(value)
            if comp.gateway not in gateway_components:
                gateway_components[comp.gateway] = {}
            gateway_components[comp.gateway][comp.id] = value

        for gateway, send_vals in gateway_components.items():
            GatewayObjectCommand(gateway, bulk_send=send_vals).publish()