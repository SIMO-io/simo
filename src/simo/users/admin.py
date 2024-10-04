from django.utils.translation import gettext_lazy as _
from django.urls.base import get_script_prefix
from django.utils.safestring import mark_safe
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin as OrgUserAdmin
from django.contrib import admin
from .models import (
    PermissionsRole, ComponentPermission, User, UserDevice, UserDeviceReportLog,
    InstanceInvitation, InstanceUser, Fingerprint
)


class ComponentPermissionInline(admin.TabularInline):
    model = ComponentPermission
    extra = 0
    fields = 'component', 'read', 'write'
    readonly_fields = 'component',

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PermissionsRole)
class PermissionsRoleAdmin(admin.ModelAdmin):
    list_display = 'name', 'is_superuser', 'is_default'
    search_fields = 'name',
    inlines = ComponentPermissionInline,

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_master:
            return qs
        return qs.filter(instance=request.instance)

    def save_model(self, request, obj, form, change):
        if not obj.id:
            obj.instance = request.instance
        obj.save()

    def get_fields(self, request, obj=None):
        if request.user.is_master:
            return super().get_fields(request, obj)
        fields = []
        for field in super().get_fields(request, obj):
            if field != 'instance':
                fields.append(field)
        return fields


class InstanceUserInline(admin.TabularInline):
    model = InstanceUser
    extra = 0
    readonly_fields = 'at_home',


@admin.register(User)
class UserAdmin(OrgUserAdmin):
    list_display = (
        'name_display', 'email', 'roles_display', 'is_master', 'is_active'
    )
    list_filter = ('is_master', )
    search_fields = ('name', 'email')
    ordering = ('name', 'email')
    filter_horizontal = ()
    fieldsets = None
    fields = (
        'name', 'email', 'is_active', 'is_master',
        'ssh_key', 'secret_key',
        'last_seen_location',
    )
    readonly_fields = (
        'name', 'email', 'avatar', 'last_action', 'is_active'
    )
    inlines = InstanceUserInline,

    def name_display(self, obj=None):
        if not obj:
            return
        avatar_url = get_script_prefix()[:-1] + '/static/img/no_avatar.png'
        if obj.avatar:
            try:
                avatar_url = obj.avatar.get_thumbnail(
                    {'size': (50, 51), 'crop': True}
                ).url
            except:
                pass
        return mark_safe(
            '<img src="{avatar_url}" style="width:25px; border-radius: 50%; margin-right:10px; margin-bottom: -8px;"></img> {user_name}'.format(
                avatar_url=avatar_url, user_name=obj.name
            )
        )
    name_display.short_description = 'Name'

    def roles_display(self, obj):
        return ', '.join([str(role) for role in obj.roles.all()])
    roles_display.short_description = 'roles'

    def has_add_permission(self, request):
        # Adding users is managed via Invitations system
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_master:
            return qs
        return qs.filter(instance_roles__instance=request.instance)


from django.contrib.auth.models import Group
admin.site.unregister(Group)


@admin.register(UserDeviceReportLog)
class UserDeviceLogInline(admin.ModelAdmin):
    model = UserDeviceReportLog
    readonly_fields = 'datetime', 'app_open', 'location', 'relay', 'users'
    list_display = 'datetime', 'app_open', 'location', 'relay', 'users'
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False

    def users(self, obj):
        return mark_safe(', '.join([
            f'<a href="{user.get_admin_url()}">{user}</a>'
            for user in obj.user_device.users.all()
        ]))

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(
            user_device__users__roles__instance=request.instance
        ).distinct()


@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = 'token', 'os', 'last_seen', 'is_primary', 'users_display'
    readonly_fields = (
        'users_display', 'token', 'os', 'last_seen',
    )
    fields = readonly_fields + ('last_seen_location', 'is_primary')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(users__roles__instance=request.instance).distinct()

    def users_display(self, obj):
        return ', '.join([str(u) for u in obj.users.all()])
    users_display.short_description = 'Users'



@admin.register(InstanceInvitation)
class InstanceInvitationAdmin(admin.ModelAdmin):
    list_display = (
        'token', 'from_user', 'to_email', 'role',
        'issue_date', 'taken_by', 'taken_date'
    )
    readonly_fields = (
        'token', 'issue_date', 'from_user', 'taken_by', 'taken_date'
    )

    actions = ['send', ]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_master:
            return qs
        return qs.filter(instance=request.instance)

    def send(self, request, queryset):
        invitations_sent = 0
        for invitation in queryset:
            sent = invitation.send()
            if sent:
                invitations_sent += 1
        if invitations_sent:
            messages.add_message(
                request, messages.SUCCESS,
                '%d invitation%s sent!' % (
                    invitations_sent, 's' if invitations_sent > 1 else ''
                )
            )
        else:
            messages.add_message(
                request, messages.ERROR,
                "No invitations were sent."
            )

@admin.register(Fingerprint)
class FingerprintAdmin(admin.ModelAdmin):
    list_display = 'value', 'type', 'date_created', 'user',
    search_fields = 'value', 'type', 'user__name', 'user__email'
    readonly_fields = 'value', 'type', 'date_created'

    def has_add_permission(self, request):
        return False
