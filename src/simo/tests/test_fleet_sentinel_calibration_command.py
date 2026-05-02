import datetime
import io

from django.core.management import call_command
from django.utils import timezone

from simo.core.models import Component, ComponentHistory, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class SentinelCalibrationCommandTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.inst.timezone = 'Europe/Vilnius'
        self.inst.save(update_fields=['timezone'])
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)

        from simo.fleet.gateways import FleetGatewayHandler

        self.gw, _ = Gateway.objects.get_or_create(type=FleetGatewayHandler.uid)
        self.th = self._mk_component('Sentinel', 'multi-sensor')
        self.reference = self._mk_component('Reference', 'numeric-sensor', value=20)

    def _mk_component(self, name, base_type, value=None):
        return Component.objects.create(
            name=name,
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type=base_type,
            controller_uid='test.Controller',
            config={},
            meta={},
            value=value,
        )

    def _history(self, component, local_dt, value):
        aware = timezone.make_aware(
            local_dt, datetime.timezone(datetime.timedelta(hours=3))
        )
        item = ComponentHistory.objects.create(
            component=component,
            type='value',
            value=value,
            alive=True,
            user=None,
        )
        ComponentHistory.objects.filter(id=item.id).update(
            date=aware.astimezone(datetime.timezone.utc)
        )

    def test_outputs_resampled_csv_with_hw2_columns(self):
        self._history(self.th, datetime.datetime(2026, 4, 29, 11, 59, 30), [
            ['outside', 21.1, 'C'],
            ['core', 25.2, 'C'],
            ['tmp1', 24.4, 'C'],
            ['tmp2', 23.9, 'C'],
            ['humidity', 44, '%'],
        ])
        self._history(self.th, datetime.datetime(2026, 4, 29, 12, 0, 45), [
            ['outside', 21.3, 'C'],
            ['core', 25.4, 'C'],
            ['tmp1', 24.6, 'C'],
            ['tmp2', 24.1, 'C'],
            ['humidity', 45, '%'],
        ])
        self._history(self.reference, datetime.datetime(2026, 4, 29, 11, 58), 20.0)
        self._history(self.reference, datetime.datetime(2026, 4, 29, 12, 1), 20.5)

        out = io.StringIO()
        call_command(
            'get_sentinel_calibration_data',
            '--th', str(self.th.id),
            '--t_real', str(self.reference.id),
            '--from', '2026-04-29 12:00',
            '--to', '2026-04-29 12:01',
            stdout=out,
        )

        self.assertEqual(out.getvalue().splitlines(), [
            'timestamp,t_real,t_aht,t_tmp,tmp1,tmp2,hum',
            '2026-04-29T12:00:00,20,21.1,25.2,24.4,23.9,44',
            '2026-04-29T12:00:30,20,21.1,25.2,24.4,23.9,44',
            '2026-04-29T12:01:00,20.5,21.3,25.4,24.6,24.1,45',
        ])

    def test_leaves_missing_tmp_columns_empty(self):
        self._history(self.th, datetime.datetime(2026, 4, 29, 12, 0), {
            'out': 21.1,
            'core': 25.2,
            'hum': 44,
        })
        self._history(self.reference, datetime.datetime(2026, 4, 29, 12, 0), 20.0)

        out = io.StringIO()
        call_command(
            'get_sentinel_calibration_data',
            '--th', str(self.th.id),
            '--t_real', str(self.reference.id),
            '--from', '2026-04-29 12:00',
            '--to', '2026-04-29 12:00:30',
            stdout=out,
        )

        self.assertEqual(out.getvalue().splitlines(), [
            'timestamp,t_real,t_aht,t_tmp,tmp1,tmp2,hum',
            '2026-04-29T12:00:00,20,21.1,25.2,,,44',
            '2026-04-29T12:00:30,20,21.1,25.2,,,44',
        ])
