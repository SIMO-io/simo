import datetime
from unittest import mock

from django.utils import timezone
from rest_framework.test import APIClient

from simo.users.models import User, UserDeviceReportLog

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class DeviceReportDeepTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        # Ensure instance has a location for at_home calcs.
        self.inst.location = '54.0,25.0'
        self.inst.save(update_fields=['location'])

        self.user = mk_user('u@example.com', 'U')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.user, self.inst, role, is_active=True)
        self.user = User.objects.get(pk=self.user.pk)

        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

    def test_negative_speed_is_clamped_and_duplicate_location_is_ignored(self):
        t0 = timezone.now()

        payload = {
            'device_token': 'dev1',
            'os': 'ios',
            'location': '54.0,25.0',
            'speed': -1,
            'app_open': True,
            'is_charging': True,
        }

        with mock.patch('simo.users.api.timezone.now', autospec=True, return_value=t0), \
                mock.patch('simo.automation.helpers.haversine_distance', autospec=True, return_value=0), \
                mock.patch('simo.users.api.dynamic_settings', {'users__at_home_radius': 1000}):
            resp = self.api.post(
                f'/api/{self.inst.slug}/users/device-report/',
                data=payload,
                format='json',
                HTTP_HOST='relay.simo.io',
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json().get('status'), 'success')
            self.assertEqual(UserDeviceReportLog.objects.count(), 1)
            log = UserDeviceReportLog.objects.first()
            self.assertEqual(log.speed_kmh, 0)

            # Duplicate report with same location within 20 seconds is accepted
            # but ignored (no new log entry).
            resp = self.api.post(
                f'/api/{self.inst.slug}/users/device-report/',
                data=payload,
                format='json',
                HTTP_HOST='relay.simo.io',
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(UserDeviceReportLog.objects.count(), 1)
