from unittest import mock

from simo.core.models import Gateway, Zone, Component

from .base import BaseSimoTestCase, mk_instance


class PresenceLightingControllerTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.auto_gw, _ = Gateway.objects.get_or_create(
            type='simo.automation.gateways.AutomationsGatewayHandler'
        )

        from simo.generic.gateways import DummyGatewayHandler
        from simo.generic.controllers import DummyBinarySensor
        from simo.automation.controllers import PresenceLighting

        self.dev_gw, _ = Gateway.objects.get_or_create(type=DummyGatewayHandler.uid)
        self.sensor = Component.objects.create(
            name='Motion',
            zone=self.zone,
            category=None,
            gateway=self.dev_gw,
            base_type='binary-sensor',
            controller_uid=DummyBinarySensor.uid,
            config={},
            meta={},
            value=False,
        )
        self.script = Component.objects.create(
            name='Presence',
            zone=self.zone,
            category=None,
            gateway=self.auto_gw,
            base_type='script',
            controller_uid=PresenceLighting.uid,
            config={
                'presence_sensors': [self.sensor.id],
                'lights': [],
                'hold_time': 1,
                'act_on': 0,
            },
            meta={},
            value='stopped',
        )

    def _controller(self, sensor_value, *, is_on=True):
        from simo.automation.controllers import PresenceLighting

        self.sensor.value = sensor_value
        controller = PresenceLighting(self.script)
        controller.sensors = {self.sensor.id: self.sensor}
        controller.is_on = is_on
        controller.hold_time = 10
        return controller

    def test_true_sensor_does_not_timeout_into_false(self):
        controller = self._controller(True)

        with mock.patch.object(controller, '_turn_it_off') as turn_off:
            with mock.patch('simo.automation.controllers.time.time', return_value=100):
                controller._on_sensor(self.sensor)
            with mock.patch('simo.automation.controllers.time.time', return_value=500):
                controller._regulate()
            with mock.patch('simo.automation.controllers.time.time', return_value=511):
                controller._regulate()

        turn_off.assert_not_called()

    def test_logs_sensor_change_and_presence_detection(self):
        controller = self._controller(True)

        with mock.patch('builtins.print') as print_mock:
            with mock.patch('simo.automation.controllers.time.time', return_value=100):
                controller._on_sensor(self.sensor)

        printed = [' '.join(str(arg) for arg in call.args) for call in print_mock.call_args_list]
        self.assertTrue(
            any(f"Sensor change: {self.sensor} -> True" in line for line in printed)
        )
        self.assertTrue(
            any(
                "Presence detected! Sensors:" in line and str(self.sensor) in line
                for line in printed
            )
        )

    def test_logs_hold_timer_start_and_expiry_before_turning_off(self):
        controller = self._controller(False)

        with (
            mock.patch('builtins.print') as print_mock,
            mock.patch.object(controller, '_turn_it_off') as turn_off,
        ):
            with mock.patch('simo.automation.controllers.time.time', return_value=100):
                controller._on_sensor(self.sensor)
            with mock.patch('simo.automation.controllers.time.time', return_value=111):
                controller._regulate()

        printed = [' '.join(str(arg) for arg in call.args) for call in print_mock.call_args_list]
        self.assertTrue(
            any(f"Sensor change: {self.sensor} -> False" in line for line in printed)
        )
        self.assertTrue(
            any("Starting hold timer for 10s" in line for line in printed)
        )
        self.assertTrue(
            any("Hold time 10s elapsed" in line for line in printed)
        )
        turn_off.assert_called_once()
