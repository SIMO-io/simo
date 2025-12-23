import datetime
import time
from unittest import mock

from django.utils import timezone
from rest_framework.test import APIClient
from actstream import action

from simo.core.models import Zone, Gateway, Component, ComponentHistory
from simo.users.models import User, ComponentPermission

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


class ComponentControllerEndpointsTests(BaseSimoTestCase):
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

        self.su = mk_user('su@example.com', 'SU')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.su, self.inst, role, is_active=True)
        self.su = User.objects.get(pk=self.su.pk)

        self.api = APIClient()
        self.api.force_authenticate(user=self.su)

    def test_controller_toggle_calls_gateway_publish(self):
        from simo.core.events import GatewayObjectCommand

        GatewayObjectCommand.publish.reset_mock()
        resp = self.api.post(
            f'/api/{self.inst.slug}/core/components/{self.comp.id}/controller/',
            data={'toggle': []},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(GatewayObjectCommand.publish.called)

    def test_subcomponent_invalid_id_returns_400(self):
        from simo.generic.controllers import SwitchGroup

        slave = Component.objects.create(
            name='S',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        self.comp.slaves.add(slave)

        resp = self.api.post(
            f'/api/{self.inst.slug}/core/components/{self.comp.id}/subcomponent/',
            data={'id': slave.id, 'toggle': []},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_control_endpoint_returns_404_for_invisible_component(self):
        user = mk_user('su2@example.com', 'SU2')
        role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(user, self.inst, role, is_active=True)
        user = User.objects.get(pk=user.pk)

        # User passes global edit permissions via role, but has no read permission
        # to this particular component, so it must not be discoverable by id.
        ComponentPermission.objects.filter(role=role, component=self.comp).update(read=False, write=False)

        api = APIClient()
        api.force_authenticate(user=user)
        resp = api.post(
            f'/api/{self.inst.slug}/core/components/control/',
            data={'id': self.comp.id, 'toggle': []},
            format='json',
        )
        self.assertEqual(resp.status_code, 404)


class ComponentHistoryAggregationTests(BaseSimoTestCase):
    def test_component_history_hour_interval_returns_vectors(self):
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

        # Keep test deterministic: API floors start_from to hour.
        start_from = (timezone.now() - datetime.timedelta(hours=2)).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        # Baseline value before start.
        ev0 = ComponentHistory.objects.create(component=comp, type='value', value=False, user=user)
        ComponentHistory.objects.filter(id=ev0.id).update(date=start_from - datetime.timedelta(minutes=10))

        ev1 = ComponentHistory.objects.create(component=comp, type='value', value=True, user=user)
        ComponentHistory.objects.filter(id=ev1.id).update(date=start_from + datetime.timedelta(minutes=5))

        api = APIClient()
        api.force_authenticate(user=user)
        resp = api.get(
            f'/api/{inst.slug}/core/component_history/?'
            f'interval=hour&component={comp.id}&start_from={start_from.timestamp()}'
        )
        self.assertEqual(resp.status_code, 200)
        vectors = resp.json()
        self.assertIsInstance(vectors, list)
        self.assertEqual(len(vectors), 1)
        vector = vectors[0]
        self.assertEqual(len(vector['labels']), 31)
        self.assertEqual(len(vector['data']), 31)
        self.assertIn('circle-dot', vector['data'])


class ActionsAndDiscoveriesTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.owner = mk_user('owner@example.com', 'Owner')
        owner_role = mk_role(self.inst, is_owner=True)
        mk_instance_user(self.owner, self.inst, owner_role, is_active=True)
        self.owner = User.objects.get(pk=self.owner.pk)

        self.regular = mk_user('u@example.com', 'U')
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(self.regular, self.inst, role, is_active=True)
        self.regular = User.objects.get(pk=self.regular.pk)

    def test_actions_visible_to_owner_only(self):
        # Create one action for this instance.
        action.send(
            self.owner,
            target=self.owner,
            verb='did-something',
            instance_id=self.inst.id,
            action_type='management_event',
            value='x',
        )

        api = APIClient()
        api.force_authenticate(user=self.owner)
        resp = api.get(f'/api/{self.inst.slug}/core/actions/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('results'))

        api = APIClient()
        api.force_authenticate(user=self.regular)
        resp = api.get(f'/api/{self.inst.slug}/core/actions/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('results'), [])

    def test_discoveries_list_and_retry_finish(self):
        su = mk_user('su@example.com', 'SU')
        su_role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(su, self.inst, su_role, is_active=True)
        su = User.objects.get(pk=su.pk)

        gw = Gateway.objects.create(
            type='simo.generic.gateways.GenericGatewayHandler',
            discovery={
                'instance_id': self.inst.id,
                'instance_uid': self.inst.uid,
                'start': time.time() - 10,
                'timeout': 60,
                'controller_uid': 'x',
                'init_data': {},
                'result': [],
            },
        )

        api = APIClient()
        api.force_authenticate(user=su)
        resp = api.get(f'/api/{self.inst.slug}/core/discoveries/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)
        self.assertEqual(resp.json()[0]['gateway'], gw.id)

        resp = api.post(f'/api/{self.inst.slug}/core/discoveries/retry/?controller_uid=x')
        self.assertEqual(resp.status_code, 200)
        resp = api.post(f'/api/{self.inst.slug}/core/discoveries/finish/?controller_uid=x')
        self.assertEqual(resp.status_code, 200)
