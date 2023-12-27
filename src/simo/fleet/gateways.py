from simo.core.gateways import BaseGatewayHandler
from simo.core.forms import BaseGatewayForm


class FleetGatewayHandler(BaseGatewayHandler):
    name = "SIMO.io Fleet"
    config_form = BaseGatewayForm
