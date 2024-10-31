from django.contrib import admin
from simo.core.middleware import get_current_instance
from .models import Notification, UserNotification


class UserNotificationInline(admin.TabularInline):
    model = UserNotification
    extra = 0


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = 'title', 'severity', 'datetime', 'to'

    inlines = UserNotificationInline,
    actions = 'dispatch',

    readonly_fields = 'instance',

    def save_model(self, request, obj, form, change):
        if not obj.id:
            obj.instance = get_current_instance()
        return super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        instance = get_current_instance()
        if instance:
            qs = qs.filter(instance=instance)
        return qs.prefetch_related('to_users')


    def to(self, obj):
        return ', '.join([str(u) for u in obj.to_users.all()])

    def dispatch(self, request, queryset):
        for item in queryset:
            item.dispatch()
        self.message_user(request, "%d notifications were dispatched." % queryset.count())
