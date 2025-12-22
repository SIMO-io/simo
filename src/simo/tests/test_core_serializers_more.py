from types import SimpleNamespace

from simo.core.models import Category, Component, Gateway, Zone

from .base import BaseSimoTestCase, mk_instance


class CoreSerializersMoreTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-a', 'A')
        self.zone = Zone.objects.create(instance=self.inst, name='Z', order=0)
        self.gw, _ = Gateway.objects.get_or_create(type='simo.generic.gateways.GenericGatewayHandler')

    def test_timestamp_field_roundtrip(self):
        from simo.core.serializers import TimestampField
        from django.utils import timezone

        f = TimestampField()
        now = timezone.now()
        ts = f.to_representation(now)
        self.assertIsInstance(ts, float)
        dt = f.to_internal_value(ts)
        self.assertEqual(int(dt.timestamp()), int(now.timestamp()))

    def test_component_many_to_many_allow_blank_returns_empty_list(self):
        from simo.core.serializers import ComponentManyToManyRelatedField

        c1 = Category.objects.create(instance=self.inst, name='C1', all=False, icon=None)
        field = ComponentManyToManyRelatedField(queryset=Category.objects.filter(pk=c1.pk), allow_blank=True)
        self.assertEqual(field.to_internal_value([]), [])

    def test_component_many_to_many_string_json_returns_queryset(self):
        from simo.core.serializers import ComponentManyToManyRelatedField

        c1 = Category.objects.create(instance=self.inst, name='C1', all=False, icon=None)
        field = ComponentManyToManyRelatedField(queryset=Category.objects.all(), allow_blank=False)
        qs = field.to_internal_value(f'[{c1.pk}]')
        self.assertEqual(list(qs.values_list('pk', flat=True)), [c1.pk])

    def test_component_many_to_many_single_int_returns_queryset(self):
        from simo.core.serializers import ComponentManyToManyRelatedField

        c1 = Category.objects.create(instance=self.inst, name='C1', all=False, icon=None)
        field = ComponentManyToManyRelatedField(queryset=Category.objects.all(), allow_blank=False)
        qs = field.to_internal_value(c1.pk)
        self.assertEqual(list(qs.values_list('pk', flat=True)), [c1.pk])

    def test_component_serializer_infers_instance_from_request_path(self):
        from simo.core.serializers import ComponentSerializer

        comp = Component.objects.create(
            name='C',
            zone=self.zone,
            category=None,
            gateway=self.gw,
            base_type='switch',
            controller_uid='x',
            config={},
            meta={},
            value=False,
        )

        req = SimpleNamespace(path=f'/core/components/{comp.id}/', build_absolute_uri=lambda p: p)
        serializer = ComponentSerializer(instance=None, context={'request': req, 'instance': self.inst})
        self.assertEqual(serializer.instance.id, comp.id)

    def test_category_serializer_thumb_none_when_no_header_image(self):
        from simo.core.serializers import CategorySerializer

        cat = Category.objects.create(instance=self.inst, name='C1', all=False, icon=None)
        req = SimpleNamespace(build_absolute_uri=lambda p: f'http://test{p}')
        ser = CategorySerializer(instance=cat, context={'request': req})
        self.assertIsNone(ser.get_header_image_thumb(cat))

    def test_formset_primary_key_related_field_get_attribute(self):
        from simo.core.serializers import FormsetPrimaryKeyRelatedField

        cat = Category.objects.create(instance=self.inst, name='C1', all=False, icon=None)
        field = FormsetPrimaryKeyRelatedField(queryset=Category.objects.all())
        field.source_attrs = ['category']
        obj = field.get_attribute({'category': cat.pk})
        self.assertEqual(obj.pk, cat.pk)
