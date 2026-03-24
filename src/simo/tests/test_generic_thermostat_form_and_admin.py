from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.template import TemplateDoesNotExist

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class ThermostatFormAndAdminTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.generic.gateways import DummyGatewayHandler, GenericGatewayHandler
        from simo.generic.controllers import DummyNumericSensor, DummyDimmer, Thermostat

        self.dev_gw, _ = Gateway.objects.get_or_create(type=DummyGatewayHandler.uid)
        self.generic_gw, _ = Gateway.objects.get_or_create(type=GenericGatewayHandler.uid)
        self.sensor = Component.objects.create(
            name='Temp',
            zone=self.zone,
            category=None,
            gateway=self.dev_gw,
            base_type='numeric-sensor',
            controller_uid=DummyNumericSensor.uid,
            config={},
            meta={},
            value=21,
            value_units='C',
        )
        self.dimmer = Component.objects.create(
            name='Cooler',
            zone=self.zone,
            category=None,
            gateway=self.dev_gw,
            base_type='dimmer',
            controller_uid=DummyDimmer.uid,
            config={'min': 0, 'max': 100},
            meta={},
            value=0,
        )
        self.thermostat = Component.objects.create(
            name='Thermostat',
            zone=self.zone,
            category=None,
            gateway=self.generic_gw,
            base_type='thermostat',
            controller_uid=Thermostat.uid,
            config={
                'temperature_sensor': self.sensor.id,
                'heaters': [],
                'coolers': [self.dimmer.id],
                'engagement': 'dynamic',
                'min': 4,
                'max': 36,
                'has_real_feel': False,
                'user_config': {},
            },
            meta={},
            value={
                'current_temp': 21,
                'target_temp': 22,
                'heating': False,
                'cooling': False,
            },
            value_units='C',
        )

    def test_thermostat_form_accepts_dimmer_for_heaters_and_coolers(self):
        from simo.generic.forms import ThermostatConfigForm
        from simo.generic.controllers import Thermostat

        form = ThermostatConfigForm(
            controller_uid=Thermostat.uid,
            data={
                'name': 'Thermostat',
                'zone': self.zone.id,
                'temperature_sensor': self.sensor.id,
                'heaters': [str(self.dimmer.id)],
                'coolers': [str(self.dimmer.id)],
                'engagement': 'dynamic',
                'min': '4',
                'max': '36',
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            [obj.id for obj in form.cleaned_data['coolers']],
            [self.dimmer.id],
        )
        self.assertEqual(
            [obj.id for obj in form.cleaned_data['heaters']],
            [self.dimmer.id],
        )

    def test_component_admin_control_falls_back_when_widget_template_is_missing(self):
        from simo.core.admin import ComponentAdmin

        admin_obj = ComponentAdmin(Component, AdminSite())
        with mock.patch(
            'simo.core.admin.render_to_string',
            side_effect=[TemplateDoesNotExist('missing'), '<div>fallback</div>'],
        ) as render_mock:
            out = admin_obj.control(self.thermostat)

        self.assertEqual(out, '<div>fallback</div>')
        self.assertEqual(
            render_mock.call_args_list[0].args[0],
            self.thermostat.controller.admin_widget_template,
        )
        self.assertEqual(
            render_mock.call_args_list[1].args[0],
            'admin/controller_widgets/generic.html',
        )
