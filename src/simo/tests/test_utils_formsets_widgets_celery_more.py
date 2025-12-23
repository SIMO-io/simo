from __future__ import annotations

from unittest import mock

from django import forms
from django.http import QueryDict
from django.test import SimpleTestCase

from simo.core.models import Zone

from .base import BaseSimoTestCase, mk_instance


class TestFormWidgets(SimpleTestCase):
    def test_admin_readonly_field_widget_renders_value_and_hidden_input(self):
        from simo.core.utils.form_widgets import AdminReadonlyFieldWidget

        w = AdminReadonlyFieldWidget()
        html = w.render('f', 'hello')
        self.assertIn('<p>hello<p>', html)
        self.assertIn('type="text"', html)
        self.assertIn('name="f"', html)

    def test_empty_field_widget_renders_empty(self):
        from simo.core.utils.form_widgets import EmptyFieldWidget

        w = EmptyFieldWidget()
        self.assertEqual(w.render('f', 'hello'), '')


class TestCeleryBeatScheduler(SimpleTestCase):
    def test_safe_persistent_scheduler_recovers_from_corruption(self):
        from celery.beat import PersistentScheduler
        from simo.core.utils.celery_beat import SafePersistentScheduler

        scheduler = SafePersistentScheduler.__new__(SafePersistentScheduler)
        scheduler._destroy_open_corrupted_schedule = mock.Mock(return_value='store')

        with mock.patch.object(
            PersistentScheduler,
            'setup_schedule',
            side_effect=[RuntimeError('bad'), 'ok'],
        ) as parent:
            value = SafePersistentScheduler.setup_schedule(scheduler)

        self.assertEqual(value, 'ok')
        self.assertEqual(parent.call_count, 2)
        scheduler._destroy_open_corrupted_schedule.assert_called_once()
        self.assertEqual(scheduler._store, 'store')


class FormsetFieldTests(BaseSimoTestCase):
    def setUp(self):
        super().setUp()
        self.inst = mk_instance('inst-fs', 'FS')
        self.z1 = Zone.objects.create(instance=self.inst, name='Z1', order=0)
        self.z2 = Zone.objects.create(instance=self.inst, name='Z2', order=1)

    def test_value_from_datadict_filters_by_prefix(self):
        from simo.core.utils.formsets import FormsetWidget

        w = FormsetWidget()
        out = w.value_from_datadict(
            {'a-0-x': '1', 'a-1-y': '2', 'b-0-x': '3'},
            {},
            'a',
        )
        self.assertEqual(out, {'a-0-x': '1', 'a-1-y': '2'})

    def test_formset_field_clean_returns_none_on_empty(self):
        from simo.core.utils.formsets import FormsetField

        class RowForm(forms.Form):
            name = forms.CharField(required=False)

        formset_cls = forms.formset_factory(RowForm, extra=0)
        field = FormsetField(formset_cls)
        self.assertIsNone(field.clean({}))

    def test_formset_field_clean_parses_and_orders(self):
        from simo.core.utils.formsets import FormsetField

        class RowForm(forms.Form):
            zone = forms.ModelChoiceField(queryset=Zone.objects.all())
            zones = forms.ModelMultipleChoiceField(queryset=Zone.objects.all(), required=False)
            enabled = forms.BooleanField(required=False)
            count = forms.IntegerField(required=False)

        formset_cls = forms.formset_factory(RowForm, extra=0, can_order=True, can_delete=True)
        field = FormsetField(formset_cls)

        prefix = field.prefix
        data = QueryDict('', mutable=True)
        data.update(
            {
                f'{prefix}-TOTAL_FORMS': '2',
                f'{prefix}-INITIAL_FORMS': '0',
                f'{prefix}-MIN_NUM_FORMS': '0',
                f'{prefix}-MAX_NUM_FORMS': '1000',
                f'{prefix}-0-zone': str(self.z1.pk),
                f'{prefix}-0-enabled': 'on',
                f'{prefix}-0-count': '7',
                f'{prefix}-0-ORDER': '1',
                f'{prefix}-1-zone': str(self.z2.pk),
                f'{prefix}-1-enabled': '',
                f'{prefix}-1-count': '',
                f'{prefix}-1-ORDER': '0',
            }
        )
        data.setlist(f'{prefix}-0-zones', [str(self.z1.pk), str(self.z2.pk)])
        data.setlist(f'{prefix}-1-zones', [str(self.z2.pk)])

        cleaned = field.clean(data)
        # ordered by ORDER (1st item has ORDER=0)
        self.assertEqual([row['zone'] for row in cleaned], [self.z2.pk, self.z1.pk])
        self.assertEqual(cleaned[0]['zones'], [self.z2.pk])
        self.assertEqual(cleaned[1]['zones'], [self.z1.pk, self.z2.pk])
        self.assertEqual(cleaned[0]['enabled'], False)
        self.assertEqual(cleaned[1]['enabled'], True)
        self.assertIsNone(cleaned[0]['count'])
        self.assertEqual(cleaned[1]['count'], 7)

    def test_formset_field_invalid_formset_sets_use_cached(self):
        from simo.core.utils.formsets import FormsetField

        class RowForm(forms.Form):
            req = forms.CharField()
            opt = forms.CharField(required=False)

        formset_cls = forms.formset_factory(RowForm, extra=0)
        field = FormsetField(formset_cls)
        prefix = field.prefix
        data = {
            f'{prefix}-TOTAL_FORMS': '1',
            f'{prefix}-INITIAL_FORMS': '0',
            f'{prefix}-MIN_NUM_FORMS': '0',
            f'{prefix}-MAX_NUM_FORMS': '1000',
            f'{prefix}-0-req': '',
            f'{prefix}-0-opt': 'x',
        }

        with self.assertRaises(forms.ValidationError):
            field.clean(data)
        self.assertTrue(field.widget.use_cached)
