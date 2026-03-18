import datetime
from unittest import mock

import pytz

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class MainStateTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('main-state-inst', 'Main State')
        self.inst.location = '54.6872,25.2797'
        self.inst.timezone = 'Europe/Vilnius'
        self.inst.save(update_fields=['location', 'timezone'])
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.generic.controllers import MainState
        from simo.generic.gateways import GenericGatewayHandler

        self.gateway, _ = Gateway.objects.get_or_create(type=GenericGatewayHandler.uid)
        self.component = Component.objects.create(
            name='Main State',
            zone=self.zone,
            category=None,
            gateway=self.gateway,
            base_type='state-select',
            controller_uid=MainState.uid,
            config={
                'is_main': True,
                'weekdays_morning_hour': 6,
                'weekends_morning_hour': 6,
                'sunday_thursday_night_hour': 21,
                'friday_saturday_night_hour': 21,
                'states': [
                    {'slug': 'morning'},
                    {'slug': 'day'},
                    {'slug': 'evening'},
                    {'slug': 'night'},
                ],
            },
            meta={},
            value='evening',
        )

    def test_same_evening_after_night_cutoff_is_not_morning(self):
        vilnius = pytz.timezone('Europe/Vilnius')
        localtime = vilnius.localize(datetime.datetime(2024, 1, 1, 21, 30, 0))
        sunrise = vilnius.localize(datetime.datetime(2024, 1, 1, 8, 0, 0))
        sunset = vilnius.localize(datetime.datetime(2024, 1, 1, 16, 0, 0))

        fake_sun = mock.Mock()
        fake_sun.get_sunrise_time.return_value = sunrise
        fake_sun.get_sunset_time.return_value = sunset

        with (
            mock.patch('simo.automation.helpers.LocalSun', autospec=True, return_value=fake_sun),
            mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=localtime),
        ):
            self.assertEqual(self.component.controller._get_day_evening_night_morning(), 'night')

    def test_pre_sunrise_after_morning_hour_is_morning(self):
        vilnius = pytz.timezone('Europe/Vilnius')
        localtime = vilnius.localize(datetime.datetime(2024, 1, 2, 6, 30, 0))
        sunrise = vilnius.localize(datetime.datetime(2024, 1, 2, 8, 0, 0))
        sunset = vilnius.localize(datetime.datetime(2024, 1, 2, 16, 0, 0))

        fake_sun = mock.Mock()
        fake_sun.get_sunrise_time.return_value = sunrise
        fake_sun.get_sunset_time.return_value = sunset

        with (
            mock.patch('simo.automation.helpers.LocalSun', autospec=True, return_value=fake_sun),
            mock.patch('simo.generic.controllers.timezone.localtime', autospec=True, return_value=localtime),
        ):
            self.assertEqual(self.component.controller._get_day_evening_night_morning(), 'morning')
