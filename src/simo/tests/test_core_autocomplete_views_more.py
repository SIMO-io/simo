from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.test import RequestFactory

from simo.core.models import Category, Component, Gateway, Icon, Zone

from .base import BaseSimoTestCase, mk_instance


class _ViewMixin:
    def _attach_request(self, view, request):
        # dal views expect these attrs
        view.request = request
        view.q = ''
        view.forwarded = {}


class AutocompleteViewsTests(BaseSimoTestCase, _ViewMixin):
    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()
        self.inst = mk_instance('inst-ac', 'AC')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.cat = Category.objects.create(instance=self.inst, name='C', icon=None, order=0, all=False)
        self.cat_all = Category.objects.create(instance=self.inst, name='All', icon=None, order=1, all=True)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        self.comp = Component.objects.create(
            name='Lamp',
            zone=self.zone,
            category=self.cat,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )
        self.icon = Icon.objects.create(slug='circle-dot', keywords='circle dot')

    def test_icon_autocomplete_filters_by_forwarded_id(self):
        from simo.core.autocomplete_views import IconModelAutocomplete

        request = self.rf.get('/x')
        view = IconModelAutocomplete()
        self._attach_request(view, request)
        view.forwarded = {'id': self.icon.pk}

        qs = view.get_queryset()
        self.assertEqual(list(qs), [self.icon])

    def test_icon_autocomplete_filters_by_value_param(self):
        from simo.core.autocomplete_views import IconModelAutocomplete

        request = self.rf.get('/x', {'value': str(self.icon.pk)})
        view = IconModelAutocomplete()
        self._attach_request(view, request)

        qs = view.get_queryset()
        self.assertEqual(list(qs), [self.icon])

    def test_icon_autocomplete_searches_by_q(self):
        from simo.core.autocomplete_views import IconModelAutocomplete

        request = self.rf.get('/x')
        view = IconModelAutocomplete()
        self._attach_request(view, request)
        view.q = 'circle'

        qs = view.get_queryset()
        self.assertIn(self.icon, list(qs))

    def test_category_autocomplete_excludes_all_true(self):
        from simo.core.autocomplete_views import CategoryAutocomplete

        request = self.rf.get('/x')
        view = CategoryAutocomplete()
        self._attach_request(view, request)

        with mock.patch('simo.core.autocomplete_views.get_current_instance', return_value=self.inst):
            qs = view.get_queryset()

        self.assertIn(self.cat, list(qs))
        self.assertNotIn(self.cat_all, list(qs))

    def test_zone_autocomplete_filters_by_current_instance(self):
        from simo.core.autocomplete_views import ZoneAutocomplete

        request = self.rf.get('/x')
        view = ZoneAutocomplete()
        self._attach_request(view, request)

        with mock.patch('simo.core.autocomplete_views.get_current_instance', return_value=self.inst):
            qs = view.get_queryset()

        self.assertEqual(list(qs), [self.zone])

    def test_component_autocomplete_filters_by_forwarded_id_list(self):
        from simo.core.autocomplete_views import ComponentAutocomplete

        request = self.rf.get('/x')
        view = ComponentAutocomplete()
        self._attach_request(view, request)
        view.forwarded = {'id': [self.comp.id]}

        with mock.patch('simo.core.autocomplete_views.get_current_instance', return_value=self.inst):
            qs = view.get_queryset()

        self.assertEqual(list(qs), [self.comp])

    def test_component_autocomplete_filters_by_base_type(self):
        from simo.core.autocomplete_views import ComponentAutocomplete

        request = self.rf.get('/x')
        view = ComponentAutocomplete()
        self._attach_request(view, request)
        view.forwarded = {'base_type': ['switch']}

        with mock.patch('simo.core.autocomplete_views.get_current_instance', return_value=self.inst):
            qs = view.get_queryset()

        self.assertEqual(list(qs), [self.comp])

    def test_component_autocomplete_filters_by_controller_uid(self):
        from simo.core.autocomplete_views import ComponentAutocomplete

        other = Component.objects.create(
            name='Other',
            zone=self.zone,
            category=self.cat,
            gateway=self.gw,
            base_type='switch',
            controller_uid='y',
            config={},
            meta={},
            value=False,
        )

        request = self.rf.get('/x')
        view = ComponentAutocomplete()
        self._attach_request(view, request)
        view.forwarded = {'controller_uid': ['x']}

        with mock.patch('simo.core.autocomplete_views.get_current_instance', return_value=self.inst):
            qs = view.get_queryset()

        self.assertEqual(list(qs), [self.comp])
        self.assertNotIn(other, list(qs))

    def test_component_autocomplete_filters_by_alarm_category_including_alarm_group(self):
        from simo.core.autocomplete_views import ComponentAutocomplete

        alarmed = Component.objects.create(
            name='Door',
            zone=self.zone,
            category=self.cat,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
            alarm_category='security',
        )
        alarm_group = Component.objects.create(
            name='Alarm Group',
            zone=self.zone,
            category=self.cat,
            gateway=self.gw,
            base_type='alarm-group',
            controller_uid='x',
            config={},
            meta={},
            value={},
        )
        other = Component.objects.create(
            name='Other',
            zone=self.zone,
            category=self.cat,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
            alarm_category='fire',
        )

        request = self.rf.get('/x')
        view = ComponentAutocomplete()
        self._attach_request(view, request)
        view.forwarded = {'alarm_category': ['security']}

        with mock.patch('simo.core.autocomplete_views.get_current_instance', return_value=self.inst):
            qs = list(view.get_queryset())

        self.assertIn(alarmed, qs)
        self.assertIn(alarm_group, qs)
        self.assertNotIn(other, qs)

    def test_component_autocomplete_q_search_matches_zone_name_and_component_name(self):
        from simo.core.autocomplete_views import ComponentAutocomplete

        zone2 = Zone.objects.create(instance=self.inst, name='Kitchen', order=1)
        comp2 = Component.objects.create(
            name='Ceiling',
            zone=zone2,
            category=self.cat,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

        request = self.rf.get('/x')
        view = ComponentAutocomplete()
        self._attach_request(view, request)
        view.q = 'Kitchen'

        with mock.patch('simo.core.autocomplete_views.get_current_instance', return_value=self.inst):
            qs = list(view.get_queryset())
        self.assertIn(comp2, qs)

        view.q = 'Lamp'
        with mock.patch('simo.core.autocomplete_views.get_current_instance', return_value=self.inst):
            qs = list(view.get_queryset())
        self.assertIn(self.comp, qs)

    def test_category_get_result_label_renders_template(self):
        from simo.core.autocomplete_views import CategoryAutocomplete

        request = self.rf.get('/x')
        view = CategoryAutocomplete()
        self._attach_request(view, request)
        with mock.patch('simo.core.autocomplete_views.render_to_string', return_value='x') as rts:
            label = view.get_result_label(self.cat)
        self.assertEqual(label, 'x')
        rts.assert_called_once()

    def test_component_autocomplete_user_agent_simo_app_uses_default_label(self):
        from simo.core.autocomplete_views import ComponentAutocomplete

        request = self.rf.get('/x')
        request.META['HTTP_USER_AGENT'] = 'SIMO-app'
        view = ComponentAutocomplete()
        self._attach_request(view, request)

        label = view.get_result_label(self.comp)
        self.assertIsInstance(label, str)

    def test_component_autocomplete_web_user_agent_renders_template(self):
        from simo.core.autocomplete_views import ComponentAutocomplete

        request = self.rf.get('/x')
        request.META['HTTP_USER_AGENT'] = 'Mozilla'
        view = ComponentAutocomplete()
        self._attach_request(view, request)

        with mock.patch('simo.core.autocomplete_views.render_to_string', return_value='x') as rts:
            label = view.get_result_label(self.comp)

        self.assertEqual(label, 'x')
        rts.assert_called_once()
