from django.contrib import admin
from django.utils.safestring import mark_safe
from django.templatetags.static import static
from .models import InstanceAccessToken


@admin.register(InstanceAccessToken)
class InstanceAccessTokenAdmin(admin.ModelAdmin):
    list_display = 'token', 'instance', 'user', 'is_valid'

    def is_valid(self, obj):
        if obj.date_expired:
            return mark_safe(
                '<img src="%s" alt="False">' % static('admin/img/icon-no.svg')
            )
        return mark_safe(
            '<img src="%s" alt="True">' % static('admin/img/icon-yes.svg')
        )