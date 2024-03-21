import os
import sys
import inspect
import time
from collections.abc import Iterable
from django.utils.text import slugify
from django.core.cache import cache
from django.utils.functional import cached_property
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from timezone_utils.choices import ALL_TIMEZONES_CHOICES
from location_field.models.plain import PlainLocationField
from model_utils import FieldTracker
from dirtyfields import DirtyFieldsMixin
from easy_thumbnails.fields import ThumbnailerImageField
from taggit.managers import TaggableManager
from simo.core.utils.mixins import SimoAdminMixin
from simo.core.storage import OverwriteStorage
from simo.core.utils.validators import validate_svg
from .managers import ZonesManager, CategoriesManager, ComponentsManager
from .events import GatewayObjectCommand, OnChangeMixin


User = get_user_model()


class Icon(DirtyFieldsMixin, models.Model, SimoAdminMixin):
    slug = models.SlugField(unique=True, db_index=True, primary_key=True)
    keywords = models.CharField(max_length=500, blank=True, null=True)
    default = models.FileField(
        "Default (off)",
        upload_to='icons', help_text=_("Only .svg file format is allowed."),
        validators=[validate_svg], storage=OverwriteStorage()
    )
    active = models.FileField(
        "Active (on)", null=True, blank=True,
        upload_to='icons', help_text=_("Only .svg file format is allowed."),
        validators=[validate_svg], storage=OverwriteStorage()
    )
    last_modified = models.DateTimeField(auto_now=True, editable=False)
    copyright = models.CharField(
        max_length=200, null=True, db_index=True,
        help_text="You are only allowed to use this icon "
                  "in SIMO.io project if this field has value."
    )

    class Meta:
        ordering = '-active', 'slug',

    def __str__(self):
        return self.slug


@receiver(post_delete, sender=Icon)
def post_icon_delete(sender, instance, *args, **kwargs):
    for file_field in ('default', 'active'):
        if not getattr(instance, file_field):
            continue
        try:
            os.remove(getattr(instance, file_field).path)
        except:
            pass


class Instance(DirtyFieldsMixin, models.Model, SimoAdminMixin):
    # Multiple home instances can be had on a single hub computer!
    # For example separate hotel apartments
    # or something of that kind.
    # Usually, there will be only one.
    uid = models.CharField(
        max_length=50, unique=True,
        help_text="Issued by SIMO.io"
    )
    name = models.CharField(max_length=100, db_index=True, unique=True)
    slug = models.CharField(max_length=100, db_index=True, unique=True)
    cover_image = ThumbnailerImageField(
        upload_to='hub_covers', null=True, blank=True
    )
    cover_image_synced = models.BooleanField(default=False)
    secret_key = models.CharField(max_length=100, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    location = PlainLocationField(null=True, blank=True, zoom=7)
    timezone = models.CharField(
        max_length=50, db_index=True, choices=ALL_TIMEZONES_CHOICES
    )
    units_of_measure = models.CharField(
        max_length=100, default='metric',
        choices=(('metric', "Metric"), ('imperial', "Imperial"))
    )
    share_location = models.BooleanField(
        default=True,
        help_text="Share exact instance location with SIMO.io remote or not?"
                  "Sharing it helps better identify if user is at home or not."

    )
    indoor_climate_sensor = models.ForeignKey(
        'Component', null=True, blank=True, on_delete=models.SET_NULL
    )
    history_days = models.PositiveIntegerField(
        default=90, help_text="How many days of component history do we keep?"
    )
    device_report_history_days = models.PositiveIntegerField(
        default=0,
        help_text="How many days of user device reports log do we keep? "
                  "Use 0 if you do not want to keep these logs at all."
    )
    learn_fingerprints_start = models.DateTimeField(null=True, blank=True)
    learn_fingerprints = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL
    )


    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        return super().save(*args, **kwargs)

    @property
    def components(self):
        return Component.objects.filter(zone__instance=self)

class Zone(DirtyFieldsMixin, models.Model, SimoAdminMixin):
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE)
    name = models.CharField(_('name'), max_length=40)
    order = models.PositiveIntegerField(
        default=0, blank=False, null=False, db_index=True
    )
    objects = ZonesManager()

    # TODO: Admin ordering not working via remote!

    class Meta:
        verbose_name = _('zone')
        verbose_name_plural = _('zones')
        ordering = ('order', 'id')

    def __str__(self):
        return self.name


class Category(DirtyFieldsMixin, models.Model, SimoAdminMixin):
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE)
    name = models.CharField(_('name'), max_length=40)
    icon = models.ForeignKey(Icon, on_delete=models.SET_NULL, null=True)
    header_image = ThumbnailerImageField(
        upload_to='categories', null=True, blank=True,
        help_text="Will be cropped down to: 830x430"
    )
    header_image_last_change = models.DateTimeField(
        auto_now_add=True, editable=False
    )
    all = models.BooleanField(
        default=False,
        help_text=_("All components automatically belongs to this category")
    )
    order = models.PositiveIntegerField(
        default=0, blank=False, null=False, db_index=True
    )
    objects = CategoriesManager()

    class Meta:
        verbose_name = _("category")
        verbose_name_plural = _("categories")
        ordering = ('order', 'id')

    def __str__(self):
        return self.name


    def save(self, *args, **kwargs):
        dirty_fields = self.get_dirty_fields()
        if 'all' in dirty_fields:
            if self.all:
                Category.objects.filter(
                    instance=self.instance
                ).update(all=False)
        if 'header_image' in dirty_fields:
            self.header_image_last_change = timezone.now()
        return super().save(*args, **kwargs)


RUN_STATUS_CHOICES_MAP = {
    'running': _("Running"), 'stopped': _("Stopped"),
    'finished': _("Finished"), 'error': _("Error")
}


class Gateway(DirtyFieldsMixin, models.Model, SimoAdminMixin):
    type = models.CharField(
        max_length=200, db_index=True, choices=(), unique=True
    )
    config = models.JSONField(_('gateway config'), default=dict, blank=True)
    status = models.CharField(
        max_length=20, null=True, blank=True, choices=(
            (key, val) for key, val in RUN_STATUS_CHOICES_MAP.items()
        ),
    )
    discovery = models.JSONField(
        null=True, blank=True, editable=False
    )


    handler = None

    def __str__(self):
        if self.handler:
            return self.handler.name
        return self.type

    def __init__(self, *args, **kwargs):
        from .utils.type_constants import get_all_gateways
        ALL_GATEWAYS = get_all_gateways()
        GATEWAYS_CHOICES = [
            (slug, cls.name) for slug, cls in ALL_GATEWAYS.items()
        ]
        GATEWAYS_CHOICES.sort(key=lambda e: e[1])
        self._meta.get_field('type').choices = GATEWAYS_CHOICES
        super().__init__(*args, **kwargs)

        gateway_class = ALL_GATEWAYS.get(self.type)
        if gateway_class:
            self.handler = gateway_class(self)
            if hasattr(self.handler, 'run'):
                setattr(self, 'run', self.handler.run)

    def start(self):
        if not hasattr(self, 'run'):
            if self.status:
                self.status = None
                self.save()
            return
        GatewayObjectCommand(self, self, set_val='start').publish()

    def stop(self):
        if not hasattr(self, 'run'):
            if self.status:
                self.status = None
                self.save()
            return
        GatewayObjectCommand(self, self, set_val='stop').publish()

    def get_socket_url(self):
        if self.id:
            return reverse_lazy(
                'ws-gateway-controller', kwargs={'gateway_id': self.id},
                urlconf=settings.CHANNELS_URLCONF
            )

    def start_discovery(self, controller_uid, init_data, timeout=None):
        self.discovery = {
            'start': time.time(),
            'timeout': timeout if timeout else 60,
            'controller_uid': controller_uid,
            'init_data': init_data,
            'result': []
        }
        self.save()

    def retry_discovery(self):
        self.discovery['start'] = time.time()
        self.discovery.pop('finished', None)
        self.save()

    def process_discovery(self, data):
        self.refresh_from_db()
        from .utils.type_constants import get_controller_types_map
        ControllerClass = get_controller_types_map().get(
            self.discovery['controller_uid']
        )
        if ControllerClass and hasattr(
            ControllerClass, '_process_discovery'
        ):
            result = ControllerClass._process_discovery(
                started_with=self.discovery['init_data'], data=data
            )
            if result:
                if not isinstance(result, dict) and isinstance(result, Iterable):
                    for res in result:
                        if isinstance(res, models.Model):
                            self.discovery['result'].append(res.pk)
                        else:
                            self.discovery['result'].append(res)
                else:
                    if isinstance(result, models.Model):
                        self.discovery['result'].append(result.pk)
                    else:
                        self.discovery['result'].append(result)

        self.save(update_fields=['discovery'])

    def finish_discovery(self):
        self.discovery['finished'] = time.time()
        self.save(update_fields=['discovery'])


class Component(DirtyFieldsMixin, models.Model, SimoAdminMixin, OnChangeMixin):
    name = models.CharField(
        _('name'), max_length=100, db_index=True
    )
    icon = models.ForeignKey(
        Icon, on_delete=models.SET_NULL, null=True, blank=True
    )
    zone = models.ForeignKey(
        Zone, related_name='components', on_delete=models.CASCADE,
    )
    category = models.ForeignKey(
        Category, related_name='components', on_delete=models.CASCADE,
        null=True, blank=True
    )
    gateway = models.ForeignKey(
        Gateway, on_delete=models.CASCADE, related_name='components'
    )
    base_type = models.CharField(
        _("base type"), max_length=200, db_index=True#, choices=BASE_TYPE_CHOICES
    )
    controller_uid = models.CharField(
        _("type"), max_length=200, choices=(), db_index=True,
    )
    config = models.JSONField(
        _('component config'), default=dict, blank=True, editable=False
    )
    meta = models.JSONField(default=dict, editable=False)
    value = models.JSONField(null=True, blank=True)
    value_previous = models.JSONField(null=True, blank=True, editable=False)
    value_units = models.CharField(max_length=100, null=True, blank=True)

    slaves = models.ManyToManyField(
        'Component', null=True, blank=True, related_name='masters'
    )

    change_init_by = models.ForeignKey(
        User, null=True, editable=False, on_delete=models.SET_NULL
    )
    change_init_date = models.DateTimeField(null=True, editable=False)
    change_init_to = models.JSONField(null=True, editable=False)
    change_init_fingerprint = models.ForeignKey(
        'users.Fingerprint', null=True, editable=False,
        on_delete=models.SET_NULL
    )
    last_change = models.DateTimeField(
        null=True, editable=False, auto_now_add=True
    )

    last_update = models.DateTimeField(auto_now=True)
    alive = models.BooleanField(default=True)
    battery_level = models.PositiveIntegerField(null=True, editable=False)

    show_in_app = models.BooleanField(default=True, db_index=True)

    # Feature for global superusers.
    # Good candidate for reworking in to something more API oriented
    # instead of injecting the code directly.
    instance_methods = models.TextField(
        blank=True, help_text=(
            'Add your own component methods or override existing ones'
        ),
        default="""

def is_in_alarm(self):
    return bool(self.value)

""")

    alarm_category = models.CharField(
        max_length=50, null=True, blank=True, db_index=True, choices=(
            ('security', _("Security")), ('fire', _("Fire")),
            ('flood', _("Flood")), ('other', _("Other"))
        ),
        help_text=_("Enable alarm properties by choosing one of alarm categories.")
    )
    arm_status = models.CharField(
        max_length=20, db_index=True, default='disarmed', choices=(
            ('disarmed', _("Disarmed")), ('pending-arm', _("Pending Arm")),
            ('armed', _("Armed")), ('breached', _("Breached"))
        )
    )

    objects = ComponentsManager()

    tracker = FieldTracker(fields=('value', 'arm_status'))
    # change this to False before saving to not record changes to history
    track_history = True

    controller_cls = None

    _mqtt_client = None
    _on_change_function = None
    _obj_ct_id = 0

    class Meta:
        verbose_name = _("Component")
        verbose_name_plural = _("Components")
        ordering = 'zone', 'base_type', 'name'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Goes in zero seconds!
        if self.instance_methods:
            custom_methods = {}
            funcType = type(self.save)
            try:
                exec(self.instance_methods, None, custom_methods)
            except:
                pass
            for key, val in custom_methods.items():
                if not callable(val):
                    continue
                setattr(self, key, funcType(val, self))

    def __str__(self):
        if self.zone:
            return '%s | %s' % (self.zone.name, self.name)
        return self.name

    @cached_property
    def controller(self):
        from .utils.type_constants import (
            get_controller_types_map,
            get_controller_types_choices
        )
        self._meta.get_field('controller_uid').choices = \
            get_controller_types_choices()
        if self.controller_uid:
            controller_cls = None
            if self.id and not 'test' in sys.argv:
                try:
                    controller_cls = cache.get('c_%d_contr_cls' % self.id)
                except:
                    pass
            if not controller_cls:
                controller_cls = get_controller_types_map(
                    self.gateway
                ).get(self.controller_uid)
                if controller_cls and self.id and not 'test' in sys.argv:
                    cache.set(
                        'c_%d_contr_cls' % self.id,
                        controller_cls, None
                    )
            if controller_cls:
                return controller_cls(self)

    def prepare_controller(self):
        if not self.controller:
            return
        controller_methods = [m for m in inspect.getmembers(
            self.controller, predicate=inspect.ismethod
        ) if not m[0].startswith('_')]
        for method in controller_methods:
            setattr(self, method[0], method[1])
        if not self.id:
            self.value = self.controller.default_value

    def get_socket_url(self):
        return reverse_lazy(
            'ws-component-controller', kwargs={'component_id': self.id},
            urlconf=settings.CHANNELS_URLCONF
        )

    def save(self, *args, **kwargs):
        from simo.users.middleware import get_current_user
        if self.alarm_category is not None:
            if self.arm_status == 'pending-arm':
                if not self.is_in_alarm():
                    self.arm_status = 'armed'
            elif self.arm_status == 'armed':
                if self.is_in_alarm():
                    self.arm_status = 'breached'
        else:
            self.arm_status = 'disarmed'

        dirty_fields = self.get_dirty_fields()

        if self.pk:
            actor = get_current_user()
            action_performed = False
            if 'value' in dirty_fields:
                ComponentHistory.objects.create(
                    component=self, type='value', value=self.value,
                    user=actor
                )
                action_performed = True
                self.last_change = timezone.now()
            if 'arm_status' in dirty_fields:
                ComponentHistory.objects.create(
                    component=self, type='security',
                    value=self.arm_status, user=actor
                )
                action_performed = True
                self.last_change = timezone.now()
            if action_performed:
                actor.last_action = timezone.now()
                actor.save()

        obj = super().save(*args, **kwargs)

        return obj

    def arm(self):
        self.refresh_from_db()
        if self.alarm_category:
            self.arm_status = 'pending-arm'
            self.save()

    def disarm(self):
        self.refresh_from_db()
        self.arm_status = 'disarmed'
        self.save()

    def is_in_alarm(self):
        return bool(self.value)

    def can_read(self, user):
        if user.is_superuser:
            return True
        perm = user.component_permissions.filter(component=self).first()
        if not perm:
            return False
        if perm.write:
            return True
        return perm.read

    def can_write(self, user):
        if user.is_superuser:
            return True
        perm = user.component_permissions.filter(component=self).first()
        if not perm:
            return False
        return perm.write


class ComponentHistory(models.Model):
    component = models.ForeignKey(
        Component, on_delete=models.CASCADE, related_name='history'
    )
    date = models.DateTimeField(auto_now_add=True, db_index=True)
    type = models.CharField(
        max_length=50, db_index=True, choices=(
            ('value', "Value"), ('security', "Security")
        )
    )
    value = models.JSONField(null=True, blank=True)
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = '-date',


class HistoryAggregate(models.Model):
    component = models.ForeignKey(
        Component, on_delete=models.CASCADE, related_name='history_aggregate'
    )
    type = models.CharField(
        max_length=50, db_index=True, choices=(
            ('value', "Value"), ('security', "Security")
        )
    )
    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField(db_index=True)
    value = models.JSONField(null=True, blank=True)

    class Meta:
        unique_together = 'component', 'type', 'start', 'end'

from .signal_receivers import *

