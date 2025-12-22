import tempfile

from django.test import Client, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from simo.core.models import Icon, Zone, Category, Gateway, Component

from .base import BaseSimoTestCase, mk_instance, mk_user, mk_role, mk_instance_user


def _results(resp):
    data = resp.json()
    return data.get('results', data)


class CoreInfoAndAuthTests(BaseSimoTestCase):
    def test_info_endpoint_is_public_and_has_cors(self):
        inst = mk_instance('inst-a', 'A')
        client = APIClient()
        resp = client.get(f'/api/{inst.slug}/core/info/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('uid'), inst.uid)
        self.assertEqual(resp.headers.get('Access-Control-Allow-Origin'), '*')

    def test_icons_list_denied_without_instance_membership(self):
        inst = mk_instance('inst-a', 'A')
        user = mk_user('u@example.com', 'U')
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.get(f'/api/{inst.slug}/core/icons/')
        self.assertEqual(resp.status_code, 403)


class CoreIconsCategoriesZonesTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.user = mk_user('su@example.com', 'SU')
        self.role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.user, self.inst, self.role, is_active=True)
        from simo.users.models import User

        self.user = User.objects.get(pk=self.user.pk)

        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

    def test_icons_list_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                icon_a = Icon.objects.create(
                    slug='test-a',
                    keywords='alpha',
                    copyright='ok',
                    default=SimpleUploadedFile(
                        'a.svg',
                        b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                        content_type='image/svg+xml',
                    ),
                )
                icon_b = Icon.objects.create(
                    slug='test-b',
                    keywords='beta',
                    copyright='ok',
                    default=SimpleUploadedFile(
                        'b.svg',
                        b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                        content_type='image/svg+xml',
                    ),
                )

        resp = self.api.get(f'/api/{self.inst.slug}/core/icons/')
        self.assertEqual(resp.status_code, 200)
        slugs = [row['slug'] for row in _results(resp)]
        self.assertIn(icon_a.slug, slugs)
        self.assertIn(icon_b.slug, slugs)

        resp = self.api.get(f'/api/{self.inst.slug}/core/icons/?slugs={icon_a.slug}')
        self.assertEqual(resp.status_code, 200)
        slugs = [row['slug'] for row in _results(resp)]
        self.assertEqual(slugs, [icon_a.slug])

        resp = self.api.get(f'/api/{self.inst.slug}/core/icons/?q=beta')
        self.assertEqual(resp.status_code, 200)
        slugs = [row['slug'] for row in _results(resp)]
        self.assertIn(icon_b.slug, slugs)

    def test_category_crud_as_superuser(self):
        resp = self.api.post(
            f'/api/{self.inst.slug}/core/categories/',
            data={'name': 'C1', 'all': False, 'icon': None},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        category_id = resp.json().get('id')
        self.assertTrue(Category.objects.filter(id=category_id, instance=self.inst).exists())

        resp = self.api.patch(
            f'/api/{self.inst.slug}/core/categories/{category_id}/',
            data={'name': 'C1-renamed'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Category.objects.get(id=category_id).name, 'C1-renamed')

        resp = self.api.get(f'/api/{self.inst.slug}/core/categories/')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in _results(resp)]
        self.assertIn(category_id, ids)

    def test_owner_cannot_delete_category(self):
        owner = mk_user('owner@example.com', 'Owner')
        owner_role = mk_role(self.inst, is_owner=True)
        mk_instance_user(owner, self.inst, owner_role, is_active=True)
        from simo.users.models import User

        owner = User.objects.get(pk=owner.pk)
        api = APIClient()
        api.force_authenticate(user=owner)

        category = Category.objects.create(instance=self.inst, name='C', icon=None, order=0)
        resp = api.delete(f'/api/{self.inst.slug}/core/categories/{category.id}/')
        self.assertEqual(resp.status_code, 403)

    def test_zone_delete_denied_when_has_components(self):
        zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        from simo.generic.controllers import SwitchGroup

        Component.objects.create(
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
        resp = self.api.delete(f'/api/{self.inst.slug}/core/zones/{zone.id}/')
        self.assertEqual(resp.status_code, 403)

    def test_zone_reorder_requires_all_zones(self):
        z1 = Zone.objects.create(instance=self.inst, name='Z1', order=0)
        Zone.objects.create(instance=self.inst, name='Z2', order=1)
        resp = self.api.post(
            f'/api/{self.inst.slug}/core/zones/reorder/',
            data={'zones': [z1.id]},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_zone_reorder_updates_order(self):
        z1 = Zone.objects.create(instance=self.inst, name='Z1', order=0)
        z2 = Zone.objects.create(instance=self.inst, name='Z2', order=1)
        resp = self.api.post(
            f'/api/{self.inst.slug}/core/zones/reorder/',
            data={'zones': [z2.id, z1.id]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        z1.refresh_from_db()
        z2.refresh_from_db()
        self.assertEqual((z2.order, z1.order), (0, 1))


class CoreSettingsStatesComponentsTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

        self.admin = mk_user('su@example.com', 'SU')
        self.role = mk_role(self.inst, is_superuser=True)
        mk_instance_user(self.admin, self.inst, self.role, is_active=True)
        from simo.users.models import User

        self.admin = User.objects.get(pk=self.admin.pk)
        self.api = APIClient()
        self.api.force_authenticate(user=self.admin)

    def test_settings_patch_validates_ranges(self):
        resp = self.api.patch(
            f'/api/{self.inst.slug}/core/settings/',
            data={'history_days': -1},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

        resp = self.api.patch(
            f'/api/{self.inst.slug}/core/settings/',
            data={'device_report_history_days': 999},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_settings_patch_updates_instance(self):
        from simo.generic.controllers import SwitchGroup

        sensor = Component.objects.create(
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

        resp = self.api.patch(
            f'/api/{self.inst.slug}/core/settings/',
            data={
                'history_days': 10,
                'device_report_history_days': 5,
                'indoor_climate_sensor': sensor.id,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.inst.refresh_from_db()
        self.assertEqual(self.inst.history_days, 10)
        self.assertEqual(self.inst.device_report_history_days, 5)
        self.assertEqual(self.inst.indoor_climate_sensor_id, sensor.id)

    def test_states_returns_timestamp_fields(self):
        from simo.generic.controllers import SwitchGroup

        Component.objects.create(
            name='C',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
            last_change=timezone.now(),
            last_modified=timezone.now(),
        )

        resp = self.api.get(f'/api/{self.inst.slug}/core/states/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('zones', data)
        self.assertIn('categories', data)
        self.assertIn('component_values', data)
        self.assertTrue(data['component_values'])
        row = data['component_values'][0]
        self.assertIsInstance(row['last_change'], float)
        self.assertIsInstance(row['last_modified'], float)

    def test_non_master_component_list_is_limited_to_permissions(self):
        from simo.generic.controllers import SwitchGroup
        from simo.users.models import ComponentPermission, User

        comp_allowed = Component.objects.create(
            name='Allowed',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )
        Component.objects.create(
            name='Denied',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
        )

        user = mk_user('u@example.com', 'U')
        role = mk_role(self.inst, is_superuser=False)
        mk_instance_user(user, self.inst, role, is_active=True)
        user = User.objects.get(pk=user.pk)
        ComponentPermission.objects.filter(role=role).delete()
        ComponentPermission.objects.create(role=role, component=comp_allowed, read=True, write=False)

        api = APIClient()
        api.force_authenticate(user=user)
        resp = api.get(f'/api/{self.inst.slug}/core/components/')
        self.assertEqual(resp.status_code, 200)
        ids = [row['id'] for row in _results(resp)]
        self.assertEqual(ids, [comp_allowed.id])


class CoreNonApiViewsTests(BaseSimoTestCase):
    def test_hub_info_includes_secret_only_without_active_instances(self):
        from simo.core.models import Instance

        Instance.objects.update(is_active=False)
        client = Client()
        resp = client.get('/api-hub-info/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('hub_uid', data)
        self.assertIn('paid_until', data)
        self.assertIn('hub_secret', data)
