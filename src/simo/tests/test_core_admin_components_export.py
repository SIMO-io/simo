from django.urls import reverse

from simo.core.models import Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance, mk_instance_user, mk_role, mk_user


class ComponentAdminExportTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.instance = mk_instance('inst-a', 'Instance A')
        self.user = mk_user('master@example.com', 'Master', is_master=True)
        self.role = mk_role(self.instance, is_superuser=True)
        mk_instance_user(self.user, self.instance, self.role, is_active=True)
        self.client.force_login(self.user)
        session = self.client.session
        session['instance_id'] = self.instance.id
        session.save()

        self.zone_a = Zone.objects.create(instance=self.instance, name='Zone A', order=0)
        self.zone_b = Zone.objects.create(instance=self.instance, name='Zone B', order=1)
        self.gateway, _ = Gateway.objects.get_or_create(
            type='simo.generic.gateways.GenericGatewayHandler'
        )

    def test_export_button_keeps_current_filters(self):
        export_url = reverse('admin:core_component_export_components_list')
        response = self.client.get(
            reverse('admin:core_component_changelist'),
            {'show_in_app__exact': '1'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{export_url}?show_in_app__exact=1"',
        )
        self.assertContains(response, 'Export Components List')

    def test_export_view_renders_filtered_grouped_components(self):
        from simo.generic.controllers import SwitchGroup

        Component.objects.create(
            name='Visible A',
            zone=self.zone_a,
            category=None,
            gateway=self.gateway,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
            show_in_app=True,
        )
        Component.objects.create(
            name='Hidden A',
            zone=self.zone_a,
            category=None,
            gateway=self.gateway,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
            show_in_app=False,
        )
        Component.objects.create(
            name='Visible B',
            zone=self.zone_b,
            category=None,
            gateway=self.gateway,
            base_type='switch',
            controller_uid=SwitchGroup.uid,
            config={},
            meta={},
            value=False,
            show_in_app=True,
        )

        response = self.client.get(
            reverse('admin:core_component_export_components_list'),
            {'show_in_app__exact': '1'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertRegex(
            response.content.decode(),
            r'(?s)Total number of components.*?2',
        )
        self.assertContains(response, 'Instance A')
        self.assertContains(response, 'Zone A')
        self.assertContains(response, 'Zone B')
        self.assertContains(response, 'Visible A')
        self.assertContains(response, 'Visible B')
        self.assertNotContains(response, 'Hidden A')
        self.assertContains(response, 'Generic | On/Off Group')
        self.assertContains(response, 'Yes')
