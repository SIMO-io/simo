from __future__ import annotations

from rest_framework.test import APIClient

from simo.core.models import Category, Component, Gateway, Zone
from simo.users.models import User

from .base import BaseSimoTestCase, mk_instance, mk_instance_user, mk_role, mk_user


class TestApiCrossInstanceIdGuessing(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst_a = mk_instance('inst-a', 'A')
        self.inst_b = mk_instance('inst-b', 'B')

        self.user_a = mk_user('a@example.com', 'A')
        role_a = mk_role(self.inst_a, is_superuser=True)
        mk_instance_user(self.user_a, self.inst_a, role_a, is_active=True)
        self.user_a = User.objects.get(pk=self.user_a.pk)

        self.api = APIClient()
        self.api.force_authenticate(user=self.user_a)

    def test_zone_id_guessing_returns_404(self):
        zone_b = Zone.objects.create(instance=self.inst_b, name='ZB', order=0)
        resp = self.api.get(f'/api/{self.inst_a.slug}/core/zones/{zone_b.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_category_id_guessing_returns_404(self):
        cat_b = Category.objects.create(instance=self.inst_b, name='CB', all=False, icon=None)
        resp = self.api.get(f'/api/{self.inst_a.slug}/core/categories/{cat_b.id}/')
        self.assertEqual(resp.status_code, 404)
        resp = self.api.patch(
            f'/api/{self.inst_a.slug}/core/categories/{cat_b.id}/',
            data={'name': 'x'},
            format='json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_component_id_guessing_returns_404(self):
        zone_b = Zone.objects.create(instance=self.inst_b, name='ZB', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        from simo.generic.controllers import SwitchGroup

        comp_b = Component.objects.create(
            name='CB',
            zone=zone_b,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        resp = self.api.get(f'/api/{self.inst_a.slug}/core/components/{comp_b.id}/')
        self.assertEqual(resp.status_code, 404)
        resp = self.api.delete(f'/api/{self.inst_a.slug}/core/components/{comp_b.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_users_viewset_id_guessing_returns_404(self):
        user_b = mk_user('b@example.com', 'B')
        role_b = mk_role(self.inst_b, is_superuser=True)
        mk_instance_user(user_b, self.inst_b, role_b, is_active=True)
        user_b = User.objects.get(pk=user_b.pk)

        resp = self.api.get(f'/api/{self.inst_a.slug}/users/users/{user_b.id}/')
        self.assertEqual(resp.status_code, 404)
        resp = self.api.patch(
            f'/api/{self.inst_a.slug}/users/users/{user_b.id}/',
            data={'is_active': False},
            format='json',
        )
        self.assertEqual(resp.status_code, 404)

