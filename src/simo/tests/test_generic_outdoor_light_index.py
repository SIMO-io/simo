import datetime

from simo.core.models import Component, ComponentHistory, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class OutdoorLightIndexTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.instance = mk_instance('outdoor-light', 'Outdoor Light')
        self.instance.location = '54.6872,25.2797'
        self.instance.save(update_fields=['location'])
        self.zone = Zone.objects.create(
            instance=self.instance, name='Other', order=0,
        )

        from simo.generic.controllers import OutdoorLightIndex, Weather
        from simo.generic.gateways import GenericGatewayHandler

        self.controller_class = OutdoorLightIndex
        self.generic_gateway, _ = Gateway.objects.get_or_create(
            type=GenericGatewayHandler.uid,
        )
        self.weather = Component.objects.create(
            name='Weather',
            zone=self.zone,
            category=None,
            gateway=self.generic_gateway,
            base_type='weather',
            controller_uid=Weather.uid,
            config={'is_main': True},
            meta={},
            value={'clouds': {'all': 0}, 'weather': [{'main': 'Clear'}]},
        )
        self.component = Component.objects.create(
            name='Outdoor Light Index',
            zone=self.zone,
            category=None,
            gateway=self.generic_gateway,
            base_type='numeric-sensor',
            controller_uid=OutdoorLightIndex.uid,
            config={},
            meta={},
            value=0,
            value_units='%',
        )

    def test_clear_day_is_brighter_than_heavy_cloud_and_night_is_dark(self):
        midday = datetime.datetime(2026, 6, 21, 9, tzinfo=datetime.timezone.utc)
        midnight = datetime.datetime(2026, 6, 21, 21, tzinfo=datetime.timezone.utc)

        clear_day = self.controller_class.calculate_index(
            self.instance.location,
            {'clouds': {'all': 0}, 'weather': [{'main': 'Clear'}]},
            current_time=midday,
        )
        heavy_cloud = self.controller_class.calculate_index(
            self.instance.location,
            {'clouds': {'all': 100}, 'weather': [{'main': 'Rain'}]},
            current_time=midday,
        )
        night = self.controller_class.calculate_index(
            self.instance.location,
            current_time=midnight,
        )

        self.assertGreater(clear_day, heavy_cloud)
        self.assertGreater(clear_day, 70)
        self.assertEqual(night, 0)

    def test_refresh_updates_the_live_value_without_creating_history(self):
        controller = self.component.controller
        midday = datetime.datetime(2026, 6, 21, 9, tzinfo=datetime.timezone.utc)

        index = controller.refresh_status(current_time=midday)

        self.component.refresh_from_db()
        self.assertEqual(self.component.value, index)
        self.assertGreater(index, 0)
        self.assertFalse(ComponentHistory.objects.filter(component=self.component).exists())

    def test_instance_defaults_include_the_outdoor_light_index(self):
        from simo.core.signal_receivers import create_instance_defaults
        from simo.generic.controllers import OutdoorLightIndex

        instance = mk_instance('outdoor-light-defaults', 'Defaults')
        create_instance_defaults(None, instance, True)

        component = Component.objects.get(
            zone__instance=instance,
            controller_uid=OutdoorLightIndex.uid,
        )
        self.assertEqual(component.value_units, '%')

