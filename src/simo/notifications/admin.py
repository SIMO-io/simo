from django.contrib import admin
from .models import Notification, UserNotification


class UserNotificationInline(admin.TabularInline):
    model = UserNotification
    extra = 0


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = 'title', 'severity', 'datetime', 'to'

    inlines = UserNotificationInline,
    actions = 'dispatch',

    def get_queryset(self, request):
        return super().get_queryset(request).filter(
            instance__in=request.user.instances
        ).prefetch_related('to_users')

    def to(self, obj):
        return ', '.join([str(u) for u in obj.to_users.all()])

    def dispatch(self, request, queryset):
        for item in queryset:
            item.dispatch()
        self.message_user(request, "%d notifications were dispatched." % queryset.count())
