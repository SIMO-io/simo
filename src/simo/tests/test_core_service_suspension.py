from unittest import mock

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class ServiceSuspensionTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

    def test_sync_service_suspension_stops_running_scripts_and_pushes_colonel_config(self):
        from simo.automation.controllers import Script
        from simo.core.service_suspension import sync_service_suspension
        from simo.fleet.gateways import FleetGatewayHandler
        from simo.fleet.models import Colonel

        auto_gw, _ = Gateway.objects.get_or_create(type='simo.automation.gateways.AutomationsGatewayHandler')
        fleet_gw, _ = Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        script = Component.objects.create(
            name='Script',
            zone=self.zone,
            category=None,
            gateway=auto_gw,
            base_type='script',
            controller_uid=Script.uid,
            config={'code': 'print("x")'},
            meta={},
            value='running',
        )
        colonel = Colonel.objects.create(
            instance=self.inst,
            uid='c-1',
            type='sentinel',
            firmware_version='1.0',
            enabled=True,
        )

        with (
            mock.patch('simo.fleet.models.Colonel.update_config', autospec=True) as update_config,
            mock.patch('simo.automation.controllers.Script.stop', autospec=True) as stop,
        ):
            sync_service_suspension(True)

        update_config.assert_called_once_with(colonel)
        stop.assert_called_once()
        script.refresh_from_db()
        self.assertTrue(script.meta.get('service_suspension_resume'))

    def test_sync_service_suspension_resumes_flagged_scripts(self):
        from simo.automation.controllers import Script
        from simo.core.service_suspension import sync_service_suspension

        auto_gw, _ = Gateway.objects.get_or_create(type='simo.automation.gateways.AutomationsGatewayHandler')
        script = Component.objects.create(
            name='Script',
            zone=self.zone,
            category=None,
            gateway=auto_gw,
            base_type='script',
            controller_uid=Script.uid,
            config={'code': 'print("x")'},
            meta={'service_suspension_resume': True},
            value='stopped',
        )

        with mock.patch('simo.automation.controllers.Script.start', autospec=True) as start:
            sync_service_suspension(False)

        start.assert_called_once()
        script.refresh_from_db()
        self.assertNotIn('service_suspension_resume', script.meta)
