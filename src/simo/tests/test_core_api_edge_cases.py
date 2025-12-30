import datetime
from unittest import mock

from django.utils import timezone
from rest_framework.test import APIClient

from simo.core.models import Zone, Gateway, Component, ComponentHistory
from simo.users.models import User, ComponentPermission

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class ComponentControllerEdgeCasesTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        self.su = mk_user('su@example.com', 'SU')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.su, self.inst, role, is_active=True)
        self.su = User.objects.get(pk=self.su.pk)
        self.api = APIClient()
        self.api.force_authenticate(user=self.su)

    def test_controller_returns_400_when_component_has_no_controller(self):
        comp = Component.objects.create(
            name='C',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='no.such.controller',
            config={},
            meta={},
            value=False,
        )
        resp = self.api.post(
            f'/api/{self.inst.slug}/core/components/{comp.id}/controller/',
            data={'toggle': []},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_controller_returns_400_on_bad_param_shape(self):
        from simo.generic.controllers import SwitchGroup

        comp = Component.objects.create(
            name='C',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        # Toggle takes no args; passing a scalar triggers a TypeError => 400.
        resp = self.api.post(
            f'/api/{self.inst.slug}/core/components/{comp.id}/controller/',
            data={'toggle': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


class ComponentValueHistoryTests(BaseSimoTestCase):
    def test_value_history_returns_metadata_and_entries(self):
        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        from simo.generic.controllers import SwitchGroup

        comp = Component.objects.create(
            name='C',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        user = mk_user('su@example.com', 'SU')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)
        user = User.objects.get(pk=user.pk)

        api = APIClient()
        api.force_authenticate(user=user)

        with mock.patch('simo.core.controllers.ControllerBase._get_value_history_chart_metadata', autospec=True, return_value=[{'label': 'Value', 'style': 'line'}]), \
                mock.patch('simo.core.controllers.ControllerBase._get_value_history', autospec=True, return_value=[[0], [1]]):
            resp = api.get(f'/api/{inst.slug}/core/components/{comp.id}/value_history/?period=day')

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['metadata'][0]['label'], 'Value')
        self.assertEqual(data['entries'], [[0], [1]])


class ComponentHistoryListAndIntervalsTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        from simo.generic.controllers import SwitchGroup

        self.comp = Component.objects.create(
            name='C',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        self.user = mk_user('u@example.com', 'U')
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(self.user, self.inst, role, is_active=True)
        self.user = User.objects.get(pk=self.user.pk)

        # Ensure role has read access to this component history.
        ComponentPermission.objects.filter(role=role, component=self.comp).update(read=True, write=False)

        ComponentHistory.objects.create(component=self.comp, type='value', value=False, user=self.user)
        ComponentHistory.objects.create(component=self.comp, type='security', value='armed', user=self.user)

        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

    def test_component_history_list_filters_by_type(self):
        resp = self.api.get(f'/api/{self.inst.slug}/core/component_history/?type=value')
        self.assertEqual(resp.status_code, 200)
        results = resp.json()['results']
        self.assertTrue(results)
        self.assertTrue(all(r['type'] == 'value' for r in results))

    def test_component_history_day_interval_returns_vectors(self):
        start_from = timezone.now() - datetime.timedelta(days=1)
        resp = self.api.get(
            f'/api/{self.inst.slug}/core/component_history/?'
            f'interval=day&component={self.comp.id}&start_from={start_from.timestamp()}'
        )
        self.assertEqual(resp.status_code, 200)
        vectors = resp.json()
        self.assertIsInstance(vectors, list)
        self.assertEqual(len(vectors), 1)
        self.assertEqual(len(vectors[0]['labels']), 25)
        self.assertEqual(len(vectors[0]['data']), 25)

    def test_component_history_interval_returns_null_when_no_controller(self):
        comp2 = Component.objects.create(
            name='NC',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='no.such.controller',
            config={},
            meta={},
            value=False,
        )
        # Give the role explicit read to pass permission gating.
        role = self.user.get_role(self.inst)
        ComponentPermission.objects.filter(role=role, component=comp2).update(read=True, write=False)

        start_from = timezone.now() - datetime.timedelta(days=1)
        resp = self.api.get(
            f'/api/{self.inst.slug}/core/component_history/?'
            f'interval=day&component={comp2.id}&start_from={start_from.timestamp()}'
        )
        self.assertEqual(resp.status_code, 200)
        # Response may be empty with no JSON renderer.
        self.assertIn(resp.content, (b'', b'null', b'null\n'))


class ValueHistoryPerformanceAndStabilityTests(BaseSimoTestCase):
    def test_value_history_day_does_not_crash_with_sparse_changes(self):
        inst = mk_instance('inst-a', 'A')
        zone = Zone.objects.create(instance=inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        from simo.core.controllers import NumericSensor

        comp = Component.objects.create(
            name='C',
            zone=zone,
            category=None,
            gateway=gw,
            base_type='numeric-sensor',
            controller_uid=NumericSensor.uid,
            config={},
            meta={},
            value=0,
        )

        user = mk_user('u@example.com', 'U')
        role = mk_role(inst, is_superuser=True)
        mk_instance_user(user, inst, role, is_active=True)
        user = User.objects.get(pk=user.pk)

        # Baseline before the 24h window.
        ev0 = ComponentHistory.objects.create(component=comp, type='value', value=0, user=user)
        ComponentHistory.objects.filter(id=ev0.id).update(
            date=timezone.now() - datetime.timedelta(hours=25)
        )

        # One sparse change inside the window that used to trigger IndexError.
        ev1 = ComponentHistory.objects.create(component=comp, type='value', value=10, user=user)
        ComponentHistory.objects.filter(id=ev1.id).update(
            date=timezone.now() - datetime.timedelta(hours=23, minutes=30)
        )

        data = comp.controller._get_value_history('day')
        self.assertEqual(len(data), 24)
        self.assertTrue(all(isinstance(item, list) and len(item) == 1 for item in data))
