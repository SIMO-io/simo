from django.contrib import admin


class ZonesFilter(admin.RelatedFieldListFilter):

    def field_choices(self, field, request, model_admin):
        ordering = self.field_admin_ordering(field, request, model_admin)
        limit_to = {'instance__in': request.user.instances}
        return field.get_choices(
            include_blank=False, ordering=ordering,
            limit_choices_to=limit_to
        )
