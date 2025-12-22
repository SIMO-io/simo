from types import SimpleNamespace
from unittest import mock

from rest_framework import serializers

from simo.core.api_meta import SIMOAPIMetadata
from simo.core.models import Category, Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class ApiMetaDetermineMetadataTests(BaseSimoTestCase):
    def test_determine_metadata_introduces_instance_from_view(self):
        inst = mk_instance('inst-a', 'A')
        meta = SIMOAPIMetadata()
        req = SimpleNamespace(resolver_match=SimpleNamespace(kwargs={'instance_slug': inst.slug}))
        view = SimpleNamespace(instance=inst)

        with (
            mock.patch('simo.core.api_meta.introduce_instance', autospec=True) as intro,
            mock.patch('rest_framework.metadata.SimpleMetadata.determine_metadata', autospec=True, return_value={'x': 1}) as det,
        ):
            out = meta.determine_metadata(req, view)

        self.assertEqual(out, {'x': 1})
        intro.assert_called_once_with(inst)
        det.assert_called_once()

    def test_determine_metadata_falls_back_to_instance_slug(self):
        inst = mk_instance('inst-a', 'A')
        meta = SIMOAPIMetadata()
        req = SimpleNamespace(resolver_match=SimpleNamespace(kwargs={'instance_slug': inst.slug}))
        view = SimpleNamespace()

        with (
            mock.patch('simo.core.api_meta.introduce_instance', autospec=True) as intro,
            mock.patch('rest_framework.metadata.SimpleMetadata.determine_metadata', autospec=True, return_value={'x': 1}),
        ):
            meta.determine_metadata(req, view)
        intro.assert_called_once_with(inst)


class ApiMetaFieldInfoTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.inst2 = mk_instance('inst-b', 'B')
        self.meta = SIMOAPIMetadata()
        self.meta.instance = self.inst

    def test_get_field_info_filters_queryset_by_instance_field(self):
        c1 = Category.objects.create(instance=self.inst, name='C1', order=0)
        Category.objects.create(instance=self.inst2, name='C2', order=0)

        form_field = SimpleNamespace(queryset=Category.objects.all())
        field = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), required=True)
        field.style = {'form_field': form_field}

        info = self.meta.get_field_info(field)

        self.assertEqual(info['type'], 'related object')
        self.assertEqual(info['required'], True)
        self.assertTrue(info['related_object'].endswith('Category'))
        self.assertEqual(list(form_field.queryset.values_list('id', flat=True)), [c1.id])

    def test_get_field_info_filters_component_queryset_by_zone_instance(self):
        z1 = Zone.objects.create(instance=self.inst, name='Z1', order=0)
        z2 = Zone.objects.create(instance=self.inst2, name='Z2', order=0)
        gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')
        c1 = Component.objects.create(
            name='C1',
            zone=z1,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )
        Component.objects.create(
            name='C2',
            zone=z2,
            category=None,
            gateway=gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

        form_field = SimpleNamespace(queryset=Component.objects.all())
        field = serializers.PrimaryKeyRelatedField(queryset=Component.objects.all())
        field.style = {'form_field': form_field}

        self.meta.get_field_info(field)
        self.assertEqual(list(form_field.queryset.values_list('id', flat=True)), [c1.id])

    def test_get_field_info_includes_choices_when_no_forward(self):
        form_field = SimpleNamespace()
        field = serializers.ChoiceField(choices=[('a', 'A'), ('b', 'B')], required=False)
        field.style = {'form_field': form_field}
        info = self.meta.get_field_info(field)

        self.assertEqual(info['type'], 'choice')
        self.assertIn('choices', info)
        self.assertEqual([c['value'] for c in info['choices']], ['a', 'b'])

    def test_get_field_info_sets_autocomplete_url_and_omits_choices_with_forward(self):
        form_field = SimpleNamespace(url='autocomplete-sound', forward={'x': 1}, zoom=7)
        field = serializers.ChoiceField(choices=[('a', 'A')])
        field.style = {'form_field': form_field}
        info = self.meta.get_field_info(field)

        self.assertIn('autocomplete_url', info)
        self.assertEqual(info['forward'], {'x': 1})
        self.assertEqual(info['zoom'], 7)
        self.assertNotIn('choices', info)

