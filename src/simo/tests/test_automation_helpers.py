import datetime
from unittest import mock

import pytz
from django.test import SimpleTestCase


class AutomationHelpersTests(SimpleTestCase):
    def test_haversine_distance_imperial_scales_from_metric(self):
        from simo.automation.helpers import haversine_distance

        metric = haversine_distance('0,0', '0,1', units_of_measure='metric')
        imperial = haversine_distance('0,0', '0,1', units_of_measure='imperial')

        self.assertGreater(metric, 0)
        self.assertAlmostEqual(imperial, metric * 3.28084, delta=1)

    def test_be_or_not_to_be_edges_and_probability(self):
        from simo.automation.helpers import be_or_not_to_be

        min_s = 10
        max_s = 20
        now = 100

        # >= max => always True
        with mock.patch('simo.automation.helpers.time.time', autospec=True, return_value=now):
            self.assertTrue(be_or_not_to_be(min_s, max_s, last_be_timestamp=now - max_s))

        # < min => always False
        with mock.patch('simo.automation.helpers.time.time', autospec=True, return_value=now):
            self.assertFalse(be_or_not_to_be(min_s, max_s, last_be_timestamp=now - (min_s - 1)))

        # Between => probabilistic
        midway = now - (min_s + (max_s - min_s) / 2)
        with (
            mock.patch('simo.automation.helpers.time.time', autospec=True, return_value=now),
            mock.patch('simo.automation.helpers.random.random', autospec=True, return_value=0.49),
        ):
            self.assertTrue(be_or_not_to_be(min_s, max_s, last_be_timestamp=midway))
        with (
            mock.patch('simo.automation.helpers.time.time', autospec=True, return_value=now),
            mock.patch('simo.automation.helpers.random.random', autospec=True, return_value=0.51),
        ):
            self.assertFalse(be_or_not_to_be(min_s, max_s, last_be_timestamp=midway))

    def test_local_sun_converts_to_local_timezone(self):
        from simo.automation.helpers import LocalSun

        utc = pytz.utc
        vilnius = pytz.timezone('Europe/Vilnius')
        local_dt = vilnius.localize(datetime.datetime(2024, 1, 1, 12, 0, 0))
        sunrise_utc = utc.localize(datetime.datetime(2024, 1, 1, 6, 0, 0))
        sunset_utc = utc.localize(datetime.datetime(2024, 1, 1, 18, 0, 0))

        with (
            mock.patch('simo.automation.helpers.Sun.get_sunrise_time', autospec=True, return_value=sunrise_utc),
            mock.patch('simo.automation.helpers.Sun.get_sunset_time', autospec=True, return_value=sunset_utc),
        ):
            sun = LocalSun('0,0')
            sunrise_local = sun.get_sunrise_time(local_dt)
            sunset_local = sun.get_sunset_time(local_dt)

        self.assertEqual(getattr(sunrise_local.tzinfo, 'zone', None), 'Europe/Vilnius')
        self.assertEqual(getattr(sunset_local.tzinfo, 'zone', None), 'Europe/Vilnius')
        self.assertEqual(sunrise_local.astimezone(utc), sunrise_utc)
        self.assertEqual(sunset_local.astimezone(utc), sunset_utc)

    def test_day_evening_night_morning_classification(self):
        from simo.automation.helpers import get_day_evening_night_morning

        class _FakeSun:
            def __init__(self, *, is_night, sunset_before):
                self._is_night = is_night
                self._sunset_before = sunset_before

            def is_night(self):
                return self._is_night

            def get_sunset_time(self, localtime):
                if self._sunset_before:
                    return localtime - datetime.timedelta(minutes=1)
                return localtime + datetime.timedelta(minutes=1)

        lt = datetime.datetime(2024, 1, 1, 12, 0, 0)
        self.assertEqual(get_day_evening_night_morning(_FakeSun(is_night=False, sunset_before=False), lt), 'day')

        lt_evening = datetime.datetime(2024, 1, 1, 20, 0, 0)
        self.assertEqual(
            get_day_evening_night_morning(_FakeSun(is_night=True, sunset_before=True), lt_evening),
            'evening',
        )

        lt_morning = datetime.datetime(2024, 1, 1, 6, 0, 0)
        self.assertEqual(
            get_day_evening_night_morning(_FakeSun(is_night=True, sunset_before=False), lt_morning),
            'morning',
        )

        lt_night = datetime.datetime(2024, 1, 1, 5, 0, 0)
        self.assertEqual(
            get_day_evening_night_morning(_FakeSun(is_night=True, sunset_before=False), lt_night),
            'night',
        )
