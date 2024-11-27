from django.contrib import admin
from django.contrib.admin.utils import (
    get_model_from_relation,
    prepare_lookup_value,
    reverse_field_path,
)
from django.utils.translation import gettext_lazy as _


class ZonesFilter(admin.RelatedFieldListFilter):

    def field_choices(self, field, request, model_admin):
        ordering = self.field_admin_ordering(field, request, model_admin)
        limit_to = {'instance__in': request.user.instances}
        return field.get_choices(
            include_blank=False, ordering=ordering,
            limit_choices_to=limit_to
        )


class AvailableChoicesFilter(admin.ChoicesFieldListFilter):
    """
    presents as choices to filter only those choices that are present in a queryset
    """

    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        parent_model, reverse_path = reverse_field_path(model, field_path)
        # Obey parent ModelAdmin queryset when deciding which options to show
        if model == parent_model:
            queryset = model_admin.get_queryset(request)
        else:
            queryset = parent_model._default_manager.all()
        self.lookup_choices = (
            queryset.distinct().order_by(field.name).values_list(
                field.name, flat=True
            )
        )


    def choices(self, changelist):
        yield {
            "selected": self.lookup_val is None,
            "query_string": changelist.get_query_string(
                remove=[self.lookup_kwarg, self.lookup_kwarg_isnull]
            ),
            "display": _("All"),
        }
        none_title = ""

        titles_map = {l:t for l, t in self.field.flatchoices}

        for val in self.lookup_choices:
            if val is None:
                none_title = titles_map.get(val, val)
                continue
            val = str(val)
            yield {
                "selected": self.lookup_val == val,
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg: val}, [self.lookup_kwarg_isnull]
                ),
                "display": titles_map.get(val, val),
            }

        if none_title:
            yield {
                "selected": bool(self.lookup_val_isnull),
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg_isnull: "True"}, [self.lookup_kwarg]
                ),
                "display": none_title,
            }
