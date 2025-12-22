from unittest import mock

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class GatesHandlerGeofenceTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.inst.location = '0,0'
        self.inst.save(update_fields=['location'])
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        self.gate = Component.objects.create(
            name='Gate',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='gate',
            controller_uid='x',
            config={'auto_open_distance': '100m', 'location': '0,0'},
            meta={},
            value=None,
        )

    def test_in_geofence_and_out_of_geofence_thresholds(self):
        from simo.automation.gateways import GatesHandler

        handler = GatesHandler()

        with mock.patch('simo.automation.gateways.haversine_distance', autospec=True, return_value=50):
            self.assertTrue(handler._is_in_geofence(self.gate, '0,1'))
            self.assertFalse(handler._is_out_of_geofence(self.gate, '0,1'))

        with mock.patch('simo.automation.gateways.haversine_distance', autospec=True, return_value=400):
            self.assertFalse(handler._is_in_geofence(self.gate, '0,1'))
            self.assertTrue(handler._is_out_of_geofence(self.gate, '0,1'))

    def test_geofence_returns_false_when_no_auto_open_distance(self):
        from simo.automation.gateways import GatesHandler

        handler = GatesHandler()

        self.gate.config.pop('auto_open_distance')
        self.gate.save(update_fields=['config'])

        with mock.patch('simo.automation.gateways.haversine_distance', autospec=True) as dist:
            self.assertFalse(handler._is_in_geofence(self.gate, '0,1'))
            self.assertFalse(handler._is_out_of_geofence(self.gate, '0,1'))
        dist.assert_not_called()

    def test_geofence_falls_back_to_instance_location_on_bad_gate_location(self):
        from simo.automation.gateways import GatesHandler

        handler = GatesHandler()
        self.gate.config['location'] = 'bad'
        self.gate.save(update_fields=['config'])

        with mock.patch(
            'simo.automation.gateways.haversine_distance',
            autospec=True,
            side_effect=[ValueError('bad gate'), 50],
        ) as dist:
            self.assertTrue(handler._is_in_geofence(self.gate, '0,1'))

        # Called once for gate.location, then for instance.location fallback.
        self.assertEqual(dist.call_count, 2)

    def test_geofence_logs_warning_and_returns_false_when_location_is_unusable(self):
        from simo.automation.gateways import GatesHandler

        handler = GatesHandler()
        self.gate.config['location'] = 'bad'
        self.gate.save(update_fields=['config'])
        self.inst.location = 'also-bad'
        self.inst.save(update_fields=['location'])

        with (
            mock.patch('simo.automation.gateways.haversine_distance', autospec=True, side_effect=ValueError('bad')),
            mock.patch.object(handler, '_log_warning', autospec=True) as warn,
        ):
            self.assertFalse(handler._is_in_geofence(self.gate, '0,1'))
        warn.assert_called_once()

