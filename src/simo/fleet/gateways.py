import datetime
from django.utils import timezone
from simo.core.gateways import BaseObjectCommandsGatewayHandler
from simo.core.forms import BaseGatewayForm
from simo.core.models import Gateway
from simo.core.events import GatewayObjectCommand



class FleetGatewayHandler(BaseObjectCommandsGatewayHandler):
    name = "SIMO.io Fleet"
    config_form = BaseGatewayForm

    periodic_tasks = (
        ('look_for_updates', 600),
        ('watch_colonels_connection', 30),
        ('push_discoveries', 3),
    )

    def _on_mqtt_message(self, client, userdata, msg):
        pass

    def look_for_updates(self):
        from .models import Colonel
        for colonel in Colonel.objects.all():
            colonel.check_for_upgrade()

    def watch_colonels_connection(self):
        from .models import Colonel
        for colonel in Colonel.objects.filter(
            socket_connected=True,
            last_seen__lt=timezone.now() - datetime.timedelta(minutes=2)
        ):
            colonel.socket_connected = False
            colonel.save()

    def push_discoveries(self):
        from .models import Colonel
        for gw in Gateway.objects.filter(
            type=self.uid,
            discovery__has_key='start',
        ).exclude(discovery__has_key='finished'):
            colonel = Colonel.objects.get(
                id=gw.discovery['init_data']['colonel']['val'][0]['pk']
            )
            print("Publish discover-ttlock command!")
            GatewayObjectCommand(
                gw, colonel, command='discover-ttlock',
            ).publish()
