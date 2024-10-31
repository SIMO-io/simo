import datetime
import requests
import subprocess
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.db import models
from django.db import transaction
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.core.cache import cache
from dirtyfields import DirtyFieldsMixin
from django.contrib.gis.geos import Point
from geopy.distance import distance
from actstream import action
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
from simo.core.middleware import get_current_instance
from .middleware import get_current_user
from .utils import rebuild_authorized_keys
from .managers import ActiveInstanceManager


class PermissionsRole(models.Model):
    instance = models.ForeignKey(
        'core.Instance', on_delete=models.CASCADE,
        help_text="Global role if instance is not set."
    )
    name = models.CharField(max_length=100, db_index=True)
    is_owner = models.BooleanField(
        default=False,
        help_text="Can manage zones, basic component parameters"
                  "and other things via SIMO.io app, but is not yet allowed "
                  "to perform any serious system changes, like superusers can."
    )
    can_manage_users = models.BooleanField(default=False)
    is_superuser = models.BooleanField(
        default=False,
        help_text="Can log in to admin interface and has all "
                  "possible permissions everywhere."
    )
    is_default = models.BooleanField(
        default=False, help_text="Default new user role."
    )

    objects = ActiveInstanceManager()

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

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.prefetch_related('instance_roles')

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
        'core.Instance', on_delete=models.CASCADE, null=True,
        related_name='instance_users',
    )
    role = models.ForeignKey(PermissionsRole, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True, db_index=True)

    at_home = models.BooleanField(default=False, db_index=True)
    last_seen = models.DateTimeField(
        null=True, blank=True,
    )
    last_seen_location = PlainLocationField(
        zoom=7, null=True, blank=True, help_text="Sent by user mobile app"
    )
    last_seen_speed_kmh = models.FloatField(default=0)
    phone_on_charge = models.BooleanField(default=False, db_index=True)

    objects = ActiveInstanceManager()

    on_change_fields = ('last_seen',)

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
    from simo.core.events import ObjectChangeEvent
    dirty_fields = instance.get_dirty_fields()
    if 'at_home' in dirty_fields or 'last_seen_location' in dirty_fields:
        def post_update():
            if 'at_home' in dirty_fields:
                if instance.at_home:
                    verb = 'came home'
                else:
                    verb = 'left'
                action.send(
                    instance.user, verb=verb,
                    instance_id=instance.instance.id,
                    action_type='user_presence', value=instance.at_home
                )
            ObjectChangeEvent(
                instance.instance, instance,  dirty_fields=dirty_fields
            ).publish()
        transaction.on_commit(post_update)
    if 'role' or 'is_active' in instance.dirty_fields:
        dynamic_settings['core__needs_mqtt_acls_rebuild'] = True


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
    is_master = models.BooleanField(
        default=False,
        help_text="Has access to everything "
                  "even without specific roles on instances."
    )
    date_joined = models.DateTimeField(auto_now_add=True)
    last_action = models.DateTimeField(
        auto_now_add=True, db_index=True,
        help_text="Last came home event or any interaction with any component."
    )
    ssh_key = models.TextField(
        null=True, blank=True,
        help_text="Will be placed in /root/.ssh/authorized_keys "
                  "if user is active and is master of a hub."
    )
    secret_key = models.CharField(
        max_length=20, db_index=True, default=get_random_string
    )

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

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
            if org.can_ssh() != self.can_ssh() or org.ssh_key != self.ssh_key:
                rebuild_authorized_keys()
        elif self.can_ssh():
            rebuild_authorized_keys()

        if not org or (org.secret_key != self.secret_key):
            self.update_mqtt_secret()

        return obj

    def update_mqtt_secret(self, reload=True):
        ps = subprocess.Popen(
            [f'mosquitto_passwd /etc/mosquitto/mosquitto_users {self.email}'],
            shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        ps.communicate(f"{self.secret_key}\n{self.secret_key}".encode())
        if reload:
            subprocess.run(
                ['service', 'mosquitto', 'reload'], stdout=subprocess.PIPE
            )

    def can_ssh(self):
        return self.is_active and self.is_master

    def get_role(self, instance):
        cache_key = f'user-{self.id}_instance-{instance.id}_role'
        role = cache.get(cache_key, 'expired')
        if role == 'expired':
            role = self.roles.filter(
                instance=instance
            ).prefetch_related(
                'component_permissions', 'component_permissions__component'
            ).first()
            cache.set(cache_key, role, 20)
        return role

    @property
    def role_id(self):
        '''Used by API serializer to get users role on a given instance.'''
        instance = get_current_instance()
        if not instance:
            return None
        cache_key = f'user-{self.id}_instance-{instance.id}-role-id'
        cached_val = cache.get(cache_key, 'expired')
        if cached_val == 'expired':
            for role in self.roles.all().select_related('instance'):
                if role.instance == instance:
                    cached_val = role.id
                    cache.set(cache_key, role.id, 20)
                    return cached_val
        return cached_val

    @role_id.setter
    def role_id(self, id):
        instance = get_current_instance()
        if not instance:
            return
        role = PermissionsRole.objects.filter(
            id=id, instance=instance
        ).first()
        if not role:
            raise ValueError("There is no such a role on this instance")

        InstanceUser.objects.update_or_create(
            user=self, instance=instance, defaults={
                'role': role
            }
        )

    @property
    def instances(self):
        from simo.core.models import Instance
        if not self.is_active:
            return Instance.objects.none()
        cache_key = f'user-{self.id}_instances'
        instances = cache.get(cache_key, 'expired')
        if instances == 'expired':
            if self.is_master:
                instances = Instance.objects.filter(is_active=True)
            else:
                instances = Instance.objects.filter(id__in=[
                    r.instance.id for r in self.instance_roles.filter(
                        is_active=True, instance__isnull=False
                    )
                ], is_active=True)
            cache.set(cache_key, instances, 10)
        return instances

    @property
    def component_permissions(self):
        return ComponentPermission.objects.filter(
            role__in=self.roles.all()
        )

    @property
    def is_active(self):
        instance = get_current_instance()
        if not instance:
            cache_key = f'user-{self.id}_is_active'
        else:
            cache_key = f'user-{self.id}_is_active_instance-{instance.id}'
        cached_value = cache.get(cache_key, 'expired')
        if cached_value == 'expired':
            if self.is_master and not self.instance_roles.all():
                # Master who have no roles on any instance are in GOD mode!
                # It can not be disabled by anybody, nor it is seen by anybody. :)
                cached_value = True
            elif instance:
                cached_value = bool(
                    self.instance_roles.filter(
                        instance=instance, is_active=True
                    ).first()
                )
            else:
                cached_value = any(
                    [ir.is_active for ir in self.instance_roles.all()]
                )
            cache.set(cache_key, cached_value, 20)
        return cached_value


    @is_active.setter
    def is_active(self, val):
        instance = get_current_instance()
        if not instance:
            return

        self.instance_roles.filter(
            instance=instance
        ).update(is_active=bool(val))
        cache_key = f'user-{self.id}_is_active_instance-{instance.id}'
        try:
            cache.delete(cache_key)
        except:
            pass

        rebuild_authorized_keys()


    @property
    def is_superuser(self):
        if self.is_master:
            return True
        for role in self.roles.all():
            if role.is_superuser:
                return True
        return False

    @property
    def is_staff(self):
        # TODO: non staff users are being redirected to simo.io sso infinitely
        if not self.is_active:
            return False
        if self.is_master:
            return True
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

    def get_component_permissions(self):
        if not self.instances:
            return []
        components = []
        for instance in self.instances:
            for comp in instance.components.all():
                can_read = comp.can_read(self)
                can_write = comp.can_write(self)
                if not any([can_read, can_write]):
                    continue
                components.append({
                    'component': comp,
                    'can_read': can_read,
                    'can_write': can_write
                })
        return components


class Fingerprint(models.Model):
    value = models.CharField(max_length=200, db_index=True, unique=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True,
        related_name='fingerprints'
    )
    name = models.CharField(max_length=100, null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    type = models.CharField(max_length=100, null=True, blank=True)


class UserDevice(models.Model, SimoAdminMixin):
    users = models.ManyToManyField(User, related_name='devices')
    os = models.CharField(max_length=100, db_index=True)
    token = models.CharField(max_length=1000, db_index=True, unique=True)
    is_primary = models.BooleanField(default=True, db_index=True)
    last_seen = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = '-last_seen',


class UserDeviceReportLog(models.Model):
    user_device = models.ForeignKey(
        UserDevice, on_delete=models.CASCADE, related_name='report_logs'
    )
    instance = models.ForeignKey(
        'core.Instance', null=True, on_delete=models.CASCADE
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
    speed_kmh = models.FloatField(default=0)
    phone_on_charge = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = '-datetime',


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


@receiver(post_save, sender=ComponentPermission)
def rebuild_mqtt_acls_on_create(sender, instance, created, **kwargs):
    if not created:
        dynamic_settings['core__needs_mqtt_acls_rebuild'] = True



@receiver(post_save, sender='core.Component')
def create_component_permissions_comp(sender, instance, created, **kwargs):
    if created:
        for role in PermissionsRole.objects.filter(
            instance=instance.zone.instance
        ):
            ComponentPermission.objects.get_or_create(
                component=instance, role=role, defaults={
                    'read': role.is_superuser or role.is_owner,
                    'write': role.is_superuser or role.is_owner
                }
            )
        dynamic_settings['core__needs_mqtt_acls_rebuild'] = True


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



class InstanceInvitation(models.Model):
    instance = models.ForeignKey('core.Instance', on_delete=models.CASCADE)
    token = models.CharField(
        max_length=50, default=get_random_string, db_index=True
    )
    role = models.ForeignKey(
        PermissionsRole, on_delete=models.CASCADE
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

    objects = ActiveInstanceManager()


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


