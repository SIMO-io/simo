from unittest import mock

from django.utils import timezone

from simo.core.models import Component, Gateway, Zone
from simo.core.middleware import introduce_instance

from .base import BaseSimoTestCase, mk_instance


class ThermostatEvaluateTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.inst.timezone = 'UTC'
        self.inst.units_of_measure = 'metric'
        self.inst.save(update_fields=['timezone', 'units_of_measure'])
        introduce_instance(self.inst)

        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        from simo.generic.controllers import Thermostat

        self.tstat = Component.objects.create(
            name='T',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='thermostat',
            controller_uid=Thermostat.uid,
            config={},
            meta={},
            value={'current_temp': 21, 'target_temp': 22, 'heating': False, 'cooling': False},
        )

    def _set_user_config_target(self, target):
        self.tstat.config['user_config'] = {
            'mode': 'auto',
            'use_real_feel': False,
            'hard': {'active': True, 'target': target},
            'daily': {'active': False, 'options': {'24h': {'active': True, 'target': target}, 'custom': []}},
            'weekly': {str(i): {'24h': {'active': True, 'target': target}, 'custom': []} for i in range(1, 8)},
        }

    def test_evaluate_sets_error_when_no_heaters_or_coolers(self):
        sensor = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='numeric-sensor',
            controller_uid='x',
            config={},
            meta={},
            value=20,
            alive=True,
        )

        self._set_user_config_target(22)
        self.tstat.config.update({'temperature_sensor': sensor.id, 'heaters': [], 'coolers': []})
        self.tstat.save(update_fields=['config'])

        self.tstat.controller._evaluate()
        self.tstat.refresh_from_db()
        self.assertEqual(self.tstat.error_msg, 'No heaters/coolers')
        self.assertFalse(self.tstat.alive)

    def test_evaluate_sets_error_when_temperature_sensor_is_missing(self):
        from simo.generic.controllers import SwitchGroup

        heater = Component.objects.create(
            name='H',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
            alive=True,
        )

        self._set_user_config_target(22)
        self.tstat.config.update({'temperature_sensor': 999, 'heaters': [heater.id], 'coolers': []})
        self.tstat.save(update_fields=['config'])

        self.tstat.controller._evaluate()
        self.tstat.refresh_from_db()
        self.assertEqual(self.tstat.error_msg, 'No temperature sensor')
        self.assertFalse(self.tstat.alive)

    def test_evaluate_static_turns_heater_on_and_off(self):
        from simo.generic.controllers import SwitchGroup

        heater = Component.objects.create(
            name='H',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
            alive=True,
        )
        sensor = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='numeric-sensor',
            controller_uid='x',
            config={},
            meta={},
            value=10,
            alive=True,
        )

        self._set_user_config_target(22)
        self.tstat.config.update(
            {
                'temperature_sensor': sensor.id,
                'heaters': [heater.id],
                'coolers': [],
                'engagement': 'static',
                'min': 4,
                'max': 36,
            }
        )
        self.tstat.save(update_fields=['config'])

        with mock.patch('simo.core.controllers.Switch.turn_on', autospec=True) as on:
            self.tstat.controller._evaluate()
        on.assert_called_once()

        # Now put temperature above high threshold -> turn_off.
        Component.objects.filter(pk=sensor.pk).update(value=30)
        with mock.patch('simo.core.controllers.Switch.turn_off', autospec=True) as off:
            self.tstat.controller._evaluate()
        off.assert_called_once()

    def test_evaluate_dynamic_uses_turn_on_when_reaction_is_full(self):
        from simo.generic.controllers import SwitchGroup

        heater = Component.objects.create(
            name='H',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
            alive=True,
        )
        sensor = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='numeric-sensor',
            controller_uid='x',
            config={},
            meta={},
            value=0,
            alive=True,
        )

        self._set_user_config_target(22)
        self.tstat.config.update(
            {
                'temperature_sensor': sensor.id,
                'heaters': [heater.id],
                'coolers': [],
                'engagement': 'dynamic',
                'user_config': dict(self.tstat.config.get('user_config', {}), mode='heater'),
            }
        )
        self.tstat.save(update_fields=['config'])

        with mock.patch('simo.core.controllers.Switch.turn_on', autospec=True) as on:
            self.tstat.controller._evaluate()
        on.assert_called_once()

