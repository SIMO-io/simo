from simo.core.gateways import BaseObjectCommandsGatewayHandler
from simo.core.forms import BaseGatewayForm
from simo.core.models import Gateway
from simo.core.events import GatewayObjectCommand



class FleetGatewayHandler(BaseObjectCommandsGatewayHandler):
    name = "SIMO.io Fleet"
    config_form = BaseGatewayForm

    periodic_tasks = (
        ('push_discoveries', 10),
    )

    def _on_mqtt_message(self, client, userdata, msg):
        pass

    def push_discoveries(self):
        from .models import Colonel
        for gw in Gateway.objects.filter(
            type=self.uid,
            discovery__has_key='start', discovery__finished=None,
        ):
            colonel = Colonel.objects.get(
                id=gw.discovery['init_data']['colonel']['val'][0]['pk']
            )
            GatewayObjectCommand(
                gw, colonel, command='discover-ttlock',
            ).publish()
