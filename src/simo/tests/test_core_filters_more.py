from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase


class TestZonesFilter(SimpleTestCase):
    def test_field_choices_limits_to_user_instances(self):
        from simo.core.filters import ZonesFilter

        field = mock.Mock()
        field.get_choices.return_value = [('1', 'Z')]

        request = SimpleNamespace(user=SimpleNamespace(instances=['i1']))
        model_admin = mock.Mock()

        f = ZonesFilter.__new__(ZonesFilter)
        f.field_admin_ordering = mock.Mock(return_value=())
        out = ZonesFilter.field_choices(f, field, request, model_admin)

        self.assertEqual(out, [('1', 'Z')])
        field.get_choices.assert_called_once()
        self.assertEqual(field.get_choices.call_args.kwargs['limit_choices_to'], {'instance__in': ['i1']})


class _DummyChangeList:
    def get_query_string(self, new_params=None, remove=None):
        new_params = new_params or {}
        remove = remove or []
        return f"params={sorted(new_params.items())}&remove={sorted(remove)}"


class TestAvailableChoicesFilter(SimpleTestCase):
    def test_choices_yields_all_and_values_and_none(self):
        from simo.core.filters import AvailableChoicesFilter

        field = SimpleNamespace(
            name='status',
            flatchoices=[('a', 'A'), ('b', 'B'), (None, 'NoneTitle')],
        )

        request = SimpleNamespace()
        params = {}
        model = SimpleNamespace()

        # ModelAdmin queryset used when parent_model == model
        model_admin = mock.Mock()
        qs = mock.Mock()
        qs.distinct.return_value.order_by.return_value.values_list.return_value = ['a', None, 'b']
        model_admin.get_queryset.return_value = qs

        with mock.patch('simo.core.filters.reverse_field_path', return_value=(model, 'x')):
            flt = AvailableChoicesFilter(field, request, params, model, model_admin, 'status')

        flt.lookup_kwarg = 'status__exact'
        flt.lookup_kwarg_isnull = 'status__isnull'
        flt.lookup_val = None
        flt.lookup_val_isnull = False
        flt.field = field

        items = list(flt.choices(_DummyChangeList()))
        self.assertEqual(items[0]['display'], 'All')
        self.assertEqual(items[0]['selected'], True)

        displays = [i['display'] for i in items]
        self.assertIn('A', displays)
        self.assertIn('B', displays)
        self.assertIn('NoneTitle', displays)

    def test_uses_parent_default_manager_when_related(self):
        from simo.core.filters import AvailableChoicesFilter

        field = SimpleNamespace(name='status', flatchoices=[('a', 'A')])
        request = SimpleNamespace()
        params = {}
        model = SimpleNamespace()
        parent_model = SimpleNamespace(_default_manager=mock.Mock())
        parent_model._default_manager.all.return_value = mock.Mock(
            distinct=mock.Mock(
                return_value=mock.Mock(
                    order_by=mock.Mock(
                        return_value=mock.Mock(values_list=mock.Mock(return_value=['a']))
                    )
                )
            )
        )
        model_admin = mock.Mock()

        with mock.patch('simo.core.filters.reverse_field_path', return_value=(parent_model, 'x')):
            AvailableChoicesFilter(field, request, params, model, model_admin, 'status')

        model_admin.get_queryset.assert_not_called()

