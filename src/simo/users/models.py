import datetime
import requests
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.db import models
from django.db.models import Q
from django.db import transaction
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver
from model_utils import FieldTracker
from dirtyfields import DirtyFieldsMixin
from django.contrib.gis.geos import Point
from geopy.distance import distance
from django.core.exceptions import ValidationError
from django.contrib.auth.models import (
    AbstractBaseUser, PermissionsMixin, UserManager as DefaultUserManager
)
from django.utils import timezone
from easy_thumbnails.fields import ThumbnailerImageField
from location_field.models.plain import PlainLocationField
from simo.conf import dynamic_settings
from simo.core.utils.mixins import SimoAdminMixin
from simo.core.utils.helpers import get_random_string
from simo.core.events import OnChangeMixin
from .middleware import get_current_user
from .utils import rebuild_authorized_keys


class PermissionsRole(models.Model):
    instance = models.ForeignKey(
        'core.Instance', null=True, blank=True, on_delete=models.CASCADE,
        help_text="Global role if instance is not set."
    )
    name = models.CharField(max_length=100, db_index=True)
    can_manage_users = models.BooleanField(default=False)
    is_superuser = models.BooleanField(
        default=False,
        help_text="Can log in to admin interface and has all "
                  "possible permissions everywhere."
    )
    is_default = models.BooleanField(
        default=False, help_text="Default new user role."
    )

    class Meta:
        verbose_name = "role"
        verbose_name_plural = "roles"

    def __str__(self):
        if not self.instance:
            return self.name
        return f"{self.name} on {self.instance}"

    def save(self, *args, **kwargs):
        obj = super().save(*args, **kwargs)
        if self.is_default:
            PermissionsRole.objects.all().exclude(
                id=self.id
            ).update(is_default=False)
        return obj


class UserManager(DefaultUserManager):

    def _create_user(self, name, email, password, **extra_fields):
        if not name:
            raise ValueError('The given name must be set')
        extra_fields.pop('first_name', None)
        extra_fields.pop('last_name', None)
        extra_fields.pop('is_staff', None)
        user = self.model(name=name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class InstanceUser(DirtyFieldsMixin, models.Model, OnChangeMixin):
    user = models.ForeignKey(
        'User', on_delete=models.CASCADE, related_name='instance_roles'
    )
    instance = models.ForeignKey(
        'core.Instance', on_delete=models.CASCADE, null=True
    )
    role = models.ForeignKey(PermissionsRole, on_delete=models.CASCADE)
    at_home = models.BooleanField(default=False)

    class Meta:
        unique_together = 'user', 'instance'

    def __str__(self):
        if self.role.instance:
            return f"{self.user} is {self.role.name} on {self.instance}"
        return f"{self.user} is {self.role.name}"

    def save(self, *args, **kwargs):
        self.instance = self.role.instance
        return super().save(*args, **kwargs)

    def get_instance(self):
        return self.instance


@receiver(post_save, sender=InstanceUser)
def post_instance_user_save(sender, instance, created, **kwargs):
    if created:
        return
    from simo.core.events import ObjectManagementEvent
    dirty_fields = instance.get_dirty_fields()
    if 'at_home' in dirty_fields:
        def post_update():
            ObjectManagementEvent(
                instance, 'changed', dirty_fields=dirty_fields
            ).publish()
        transaction.on_commit(post_update)


class User(AbstractBaseUser, SimoAdminMixin):
    name = models.CharField(_('name'), max_length=150)
    email = models.EmailField(_('email address'), unique=True)
    avatar = ThumbnailerImageField(
        upload_to='avatars', null=True, blank=True,
        help_text=_("Comes from SIMO.io"),
    )
    avatar_url = models.URLField(null=True, blank=True)
    avatar_last_change = models.DateTimeField(auto_now_add=True)
    roles = models.ManyToManyField(PermissionsRole, through=InstanceUser)
    is_active = models.BooleanField(
        _('active'),
        default=True,
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )
    date_joined = models.DateTimeField(auto_now_add=True)
    last_action = models.DateTimeField(
        auto_now_add=True, db_index=True,
        help_text="Last came home event or any interaction with any component."
    )
    ssh_key = models.TextField(
        null=True, blank=True,
        help_text="DO NOT EDIT IT MANUALLY! Comes from SIMO.io. <br>"
                  "Will be placed in /root/.ssh/authorized_keys "
                  "if user is active and has superuser rights."
    )
    last_seen_location = PlainLocationField(
        zoom=7, null=True, blank=True, help_text="Sent by user mobile app"
    )
    last_seen_location_datetime = models.DateTimeField(
        null=True, blank=True,
    )
    secret_key = models.CharField(
        max_length=20, db_index=True, default=get_random_string
    )


    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    _instances = None
    _instance = None

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')
        abstract = False

    def __str__(self):
        return self.name

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name

    def save(self, *args, **kwargs):
        try:
            org = User.objects.get(pk=self.pk)
        except:
            org = None
        obj = super().save(*args, **kwargs)

        if org:
            if org.can_ssh() != self.can_ssh():
                rebuild_authorized_keys()
        elif self.can_ssh():
            rebuild_authorized_keys()
        elif org and org.ssh_key != self.ssh_key:
            rebuild_authorized_keys()

        return obj

    def can_ssh(self):
        return self.is_active and self.ssh_key and self.is_superuser

    def get_role(self, instance):
        for role in self.roles.all():
            if not role.instance:
                return role
        for role in self.roles.all():
            if role.instance == instance:
                return role

    def set_instance(self, instance):
        self._instance = instance

    @property
    def role_id(self):
        '''Used by API serializer to get users role on a given instance.'''
        if not self._instance:
            return None
        for role in self.roles.all():
            if role.instance == self._instance:
                return role.id
        return None

    @role_id.setter
    def role_id(self, id):
        if not self._instance:
            return
        role = PermissionsRole.objects.filter(
            id=id, instance=self._instance
        ).first()
        if not role:
            raise ValueError("There is no such a role on this instance")

        InstanceUser.objects.update_or_create(
            user=self, instance=self._instance, defaults={
                'role': role
            }
        )

    @property
    def instances(self):
        if self._instances != None:
            return self._instances
        from simo.core.models import Instance

        self._instances = set()
        for role in self.roles.all():
            if not role.instance:
                self._instances = set(Instance.objects.all())
                return self._instances
            self._instances.add(role.instance)
        return self._instances

    @property
    def is_master(self):
        for role in self.roles.all():
            if not role.instance:
                return True
        return False

    @property
    def component_permissions(self):
        return ComponentPermission.objects.filter(
            role__in=self.roles.all()
        )

    @property
    def is_superuser(self):
        for role in self.roles.all():
            if not role.instance and role.is_superuser:
                return True
        return False

    @property
    def is_staff(self):
        # TODO: inactive users are being redirected to simo.io sso infinitely
        if not self.is_active:
            return False
        for role in self.roles.all():
            if role.is_superuser:
                return True
        return False

    @property
    def primary_device_token(self):
        device = self.devices.filter(is_primary=True).first()
        if not device:
            return
        return '--'.join([device.os, device.token])

    def has_perm(self, perm, obj=None):
        return True

    def has_module_perms(self, app_label):
        return True

    def has_perms(self, perm_list, obj=None):
        return True


@receiver(post_save, sender=User)
def post_user_save(sender, instance, created, **kwargs):
    from simo.core.events import ObjectManagementEvent
    def post_update():
        if created:
            ObjectManagementEvent(instance, 'added').publish()
        else:
            ObjectManagementEvent(instance, 'changed').publish()

    transaction.on_commit(post_update)


@receiver(post_delete, sender=User)
def post_delete_management_event(sender, instance, *args, **kwargs):
    from simo.core.events import ObjectManagementEvent
    ObjectManagementEvent(instance, 'removed').publish()


class UserDevice(models.Model, SimoAdminMixin):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='devices'
    )
    os = models.CharField(max_length=100, db_index=True)
    token = models.CharField(max_length=1000, db_index=True, unique=True)
    is_primary = models.BooleanField(default=True, db_index=True)
    last_seen = models.DateTimeField(auto_now_add=True, db_index=True)
    last_seen_location = PlainLocationField(zoom=7, null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.is_primary:
            UserDevice.objects.filter(user=self.user).exclude(
                pk=self.pk
            ).update(is_primary=False)
        return super().save(*args, **kwargs)

    class Meta:
        ordering = '-last_seen',


class UserDeviceReportLog(models.Model):
    user_device = models.ForeignKey(
        UserDevice, on_delete=models.CASCADE, related_name='report_logs'
    )
    datetime = models.DateTimeField(auto_now_add=True)
    app_open = models.BooleanField(
        default=False, help_text="Sent while using app or by background process."
    )
    relay = models.CharField(
        max_length=200, null=True, blank=True,
        help_text="Sent via remote relay if specified, otherwise it's from LAN."
    )
    location = PlainLocationField(zoom=7, null=True, blank=True)

    class Meta:
        ordering = '-datetime',


@receiver(post_save, sender=UserDeviceReportLog)
def set_user_at_home(sender, instance, created, **kwargs):
    from simo.core.models import Instance
    if not created:
        return
    if not instance.relay:
        for item in InstanceUser.objects.filter(user=instance.user_device.user):
            item.at_home = True
            item.save()
        return
    if not instance.location:
        return

    for instance in Instance.objects.all():
        cords = instance.location
        try:
            instance_location = Point(
                [float(cords.split(',')[0]), float(cords.split(',')[1])],
                srid=4326
            )
        except:
            return
        try:
            log_location = Point(
                [
                    float(instance.location.split(',')[0]),
                    float(cords.instance.location(',')[1])
                ], srid=4326
            )
        except:
            return
        else:
            for item in InstanceUser.objects.filter(
                    user=instance.user_device.user, instance=instance
            ):
                item.at_home = distance(
                    instance_location, log_location
                ).meters < dynamic_settings['users__at_home_radius']
                item.save()


class ComponentPermission(models.Model):
    role = models.ForeignKey(
        PermissionsRole, on_delete=models.CASCADE,
        related_name='component_permissions'
    )
    component = models.ForeignKey(
        'core.Component', on_delete=models.CASCADE
    )
    read = models.BooleanField(default=False)
    write = models.BooleanField(default=False)

    def __str__(self):
        return ''


@receiver(post_save, sender='core.Component')
def create_component_permissions_comp(sender, instance, created, **kwargs):
    if created:
        for role in PermissionsRole.objects.filter(
            Q(instance__isnull=True) | Q(instance=instance.zone.instance)
        ):
            ComponentPermission.objects.get_or_create(
                component=instance, role=role, defaults={
                    'read': role.is_superuser, 'write': role.is_superuser
                }
            )


@receiver(post_save, sender=PermissionsRole)
def create_component_permissions_role(sender, instance, created, **kwargs):
    if created:
        from simo.core.models import Component
        components_qs = Component.objects.all()
        if instance.instance:
            components_qs = components_qs.filter(zone__instance=instance.instance)
        for comp in components_qs:
            ComponentPermission.objects.get_or_create(
                component=comp, role=instance, defaults={
                    'read': instance.is_superuser, 'write': instance.is_superuser
                }
            )


def get_default_inviation_expire_date():
    return timezone.now() + datetime.timedelta(days=14)


def get_default_invitation_role():
    role = PermissionsRole.objects.filter(is_default=True).first()
    if not role:
        return PermissionsRole.objects.all().first().id
    return role.id


class InstanceInvitation(models.Model):
    instance = models.ForeignKey('core.Instance', on_delete=models.CASCADE)
    token = models.CharField(
        max_length=50, default=get_random_string, db_index=True
    )
    role = models.ForeignKey(
        PermissionsRole, on_delete=models.CASCADE,
        default=get_default_invitation_role
    )
    issue_date = models.DateTimeField(auto_now_add=True)
    expire_date = models.DateTimeField(
        default=get_default_inviation_expire_date
    )
    from_user = models.ForeignKey(
        User, blank=True, null=True, on_delete=models.CASCADE,
        related_name='issued_hub_invitations'
    )
    to_email = models.EmailField(blank=True, null=True)
    last_sent = models.DateTimeField(null=True, blank=True)
    taken_by = models.ForeignKey(
        User, blank=True, null=True, on_delete=models.CASCADE,
        related_name='accepted_hub_invitations'
    )
    taken_date = models.DateTimeField(null=True, blank=True)


    class Meta:
        verbose_name = "invitation"
        verbose_name_plural = "invitations"

    def __str__(self):
        return self.token

    def save(self, *args, **kwargs):
        if not self.from_user:
            self.from_user = get_current_user()
        return super().save(*args, **kwargs)

    def send(self):
        if not self.to_email:
            return
        response = requests.post(
            'https://simo.io/hubs/invitation-send/', json={
                'instance_uid': self.instance.uid,
                'hub_secret': dynamic_settings['core__hub_secret'],
                'token': self.token,
                'from_user_name': self.from_user.name,
                'to_email': self.to_email,
                'expire_date': self.expire_date.timestamp(),
                'absolute_url': self.get_absolute_url()
            }
        )
        if response.status_code == 200:
            self.last_sent = timezone.now()
            self.save()
        return response

    def get_absolute_url(self):
        return reverse('accept_invitation', kwargs={'token': self.token})