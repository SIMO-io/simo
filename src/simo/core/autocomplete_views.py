from dal import autocomplete
from django.db.models import Q
from django.template.loader import render_to_string
from simo.core.utils.helpers import search_queryset
from .models import Icon, Category, Zone, Component


class IconModelAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        qs = Icon.objects.all()

        if not self.request.user.is_staff:
            return qs.none()

        if self.forwarded.get("id"):
            return qs.filter(pk=self.forwarded.get("id"))

        if self.q:
            qs = search_queryset(qs, self.q, ('slug', 'keywords'))
        return qs.distinct()

    def get_result_label(self, item):
        return render_to_string(
            'core/icon_acutocomplete_select_item.html', {
                'icon': item,
            }
        )

    def get_selected_result_label(self, item):
        return self.get_result_label(item)


# class IconSlugAutocomplete(autocomplete.Select2ListView):
#
#     def get_list(self):
#         if not self.request.user.is_staff:
#             return []
#
#         try:
#             esp_device = Colonel.objects.get(
#                 pk=self.forwarded.get("colonel")
#             )
#         except:
#             return []
#
#         return get_gpio_pins_choices(
#             esp_device, self.forwarded.get('filters'),
#             self.forwarded.get('self')
#         )


class CategoryAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        qs = Category.objects.all()


        if not self.request.user.is_staff:
            return qs.none()

        if self.forwarded.get("id"):
            return qs.filter(pk=self.forwarded.get("id"))

        qs = qs.filter(all=False)
        if self.q:
            qs = search_queryset(qs, self.q, ('name'))
        return qs.distinct()

    def get_result_label(self, item):
        return render_to_string(
            'core/object_acutocomplete_select_item.html', {
                'object': item
            }
        )

    def get_selected_result_label(self, item):
        return self.get_result_label(item)


class ZoneAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        qs = Zone.objects.all()

        if not self.request.user.is_staff:
            return qs.none()

        if self.forwarded.get("id"):
            return qs.filter(pk=self.forwarded.get("id"))

        if self.q:
            qs = search_queryset(qs, self.q, ('name',))
        return qs.distinct()

    def get_result_label(self, item):
        return render_to_string(
            'core/object_acutocomplete_select_item.html', {
                'object': item
            }
        )

    def get_selected_result_label(self, item):
        return self.get_result_label(item)


class ComponentAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        qs = Component.objects.all()

        if not self.request.user.is_staff:
            return qs.none()

        if self.forwarded.get("id"):
            if isinstance(self.forwarded['id'], list):
                return qs.filter(pk__in=self.forwarded["id"])
            return qs.filter(pk=self.forwarded.get("id"))

        if 'base_type' in self.forwarded:
            qs = qs.filter(base_type__in=self.forwarded['base_type'])

        if 'controller_uid' in self.forwarded:
            qs = qs.filter(controller_uid__in=self.forwarded['controller_uid'])

        if 'alarm_category' in self.forwarded:
            qs = qs.filter(
                Q(base_type='alarm-group') |
                Q(alarm_category__in=self.forwarded['alarm_category'])
            )

        if self.q:
            qs = search_queryset(qs, self.q, ('name',))
        return qs.distinct()

    def get_result_label(self, item):
        return render_to_string(
            'core/object_acutocomplete_select_item.html', {
                'object': item
            }
        )

    def get_selected_result_label(self, item):
        return self.get_result_label(item)
