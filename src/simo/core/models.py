import inspect
import time
from collections.abc import Iterable
from django.utils.text import slugify
from django.utils.functional import cached_property
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from timezone_utils.choices import ALL_TIMEZONES_CHOICES
from location_field.models.plain import PlainLocationField
from model_utils import FieldTracker
from dirtyfields import DirtyFieldsMixin
from simo.core.utils.mixins import SimoAdminMixin
from simo.core.storage import OverwriteStorage
from simo.core.utils.validators import validate_svg
from simo.core.utils.helpers import get_random_string
from simo.users.models import User
from .managers import (
    InstanceManager, ZonesManager, CategoriesManager, ComponentsManager
)
from .events import GatewayObjectCommand, OnChangeMixin


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


class Instance(models.Model, SimoAdminMixin):
    # Multiple home instances can be had on a single hub computer!
    # For example separate hotel apartments
    # or something of that kind.
    # Usually, there will be only one.
    uid = models.CharField(
        max_length=50, unique=True, help_text="Issued by SIMO.io"
    )
    name = models.CharField(max_length=100, db_index=True)
    slug = models.CharField(max_length=100, db_index=True)
    date_created = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(
        default=True, db_index=True,
        help_text="Get's deactivated instead of delete."
    )
    location = PlainLocationField(null=True, blank=True, zoom=7)
    timezone = models.CharField(
        max_length=50, db_index=True, choices=ALL_TIMEZONES_CHOICES
    )
    units_of_measure = models.CharField(
        max_length=100, default='metric',
        choices=(('metric', "Metric"), ('imperial', "Imperial"))
    )
    indoor_climate_sensor = models.ForeignKey(
        'Component', null=True, blank=True, on_delete=models.SET_NULL,
        limit_choices_to={'base_type__in': ['numeric-sensor', 'multi-sensor']}
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

    objects = InstanceManager()


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
    header_image = models.ImageField(
        upload_to='categories', null=True, blank=True,
        help_text="Will be cropped down to: 830x430"
    )
    all = models.BooleanField(
        default=False,
        help_text=_("All components automatically belongs to this category")
    )
    last_modified = models.DateTimeField(auto_now=True, editable=False)
    order = models.PositiveIntegerField(
        blank=False, null=False, db_index=True
    )
    objects = CategoriesManager()

    class Meta:
        verbose_name = _("category")
        verbose_name_plural = _("categories")
        ordering = ('order', 'id')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.order is None:
            last_cat = Category.objects.filter(instance=self.instance).last()
            if last_cat:
                self.order = last_cat.order + 1
            else:
                self.order = 0
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
        from .utils.type_constants import GATEWAYS_MAP, GATEWAYS_CHOICES
        self._meta.get_field('type').choices = GATEWAYS_CHOICES
        super().__init__(*args, **kwargs)

        gateway_class = GATEWAYS_MAP.get(self.type)
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
        if self.discovery.get('finished'):
            print(
                f"Gateway is not in pairing mode at the moment!"
            )
            return
        if self.discovery['controller_uid'] != data.get('type'):
            print(f"Gateway is not in pairing mode for {self.discovery['controller_uid']} "
                  f"but not for {data.get('type')} at the moment!")
            return

        from .utils.type_constants import CONTROLLER_TYPES_MAP
        ControllerClass = CONTROLLER_TYPES_MAP.get(data.get('type'))
        if not hasattr(ControllerClass, '_process_discovery'):
            print(f"{data.get('type')} controller has no _process_discovery method." )
            return

        result = ControllerClass._process_discovery(
            started_with=self.discovery['init_data'], data=data
        )
        if result:
            self.refresh_from_db()
            if not isinstance(result, dict) and isinstance(result, Iterable):
                for res in result:
                    if isinstance(res, models.Model):
                        if res.pk not in self.discovery['result']:
                            self.discovery['result'].append(res.pk)
                    else:
                        if res not in self.discovery['result']:
                            self.discovery['result'].append(res)
            else:
                if isinstance(result, models.Model):
                    if result.pk not in self.discovery['result']:
                        self.discovery['result'].append(result.pk)
                else:
                    if result not in self.discovery['result']:
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
        null=True, editable=False, auto_now_add=True,
        help_text="Last time component state was changed."
    )
    last_modified = models.DateTimeField(
        auto_now_add=True, db_index=True, editable=False,
        help_text="Last time component was modified."
    )

    last_update = models.DateTimeField(auto_now=True)
    alive = models.BooleanField(default=True)
    error_msg = models.TextField(null=True, blank=True, editable=False)
    battery_level = models.PositiveIntegerField(null=True, editable=False)

    show_in_app = models.BooleanField(default=True, db_index=True)

    notes = models.TextField(null=True, blank=True)

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
        help_text=_(
            "Enable alarm properties by choosing one of alarm categories."
        )
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

    _controller_initiated = False

    _mqtt_client = None
    _on_change_function = None
    _obj_ct_id = 0

    class Meta:
        verbose_name = _("Component")
        verbose_name_plural = _("Components")
        ordering = 'zone', 'base_type', 'name'

    def __str__(self):
        if self.zone:
            return '%s | %s' % (self.zone.name, self.name)
        return self.name

    def __getattribute__(self, attr):
        try:
            return super().__getattribute__(attr)
        except Exception as e:
            if not attr.startswith('_') and not self._controller_initiated:
                self._controller_initiated = True
                self.prepare_controller()
                return super().__getattribute__(attr)
            raise e

    @cached_property
    def controller(self):
        from .utils.type_constants import (
            CONTROLLERS_BY_GATEWAY,
            CONTROLLER_TYPES_CHOICES
        )
        self._meta.get_field('controller_uid').choices = CONTROLLER_TYPES_CHOICES
        if self.controller_uid:
            self.controller_cls = None
            if not self.controller_cls:
                self.controller_cls = CONTROLLERS_BY_GATEWAY.get(
                    self.gateway.type, {}
                ).get(self.controller_uid)
            if self.controller_cls:
                return self.controller_cls(self)

    def prepare_controller(self):
        if self.controller:
            controller_methods = [m for m in inspect.getmembers(
                self.controller, predicate=inspect.ismethod
            ) if not m[0].startswith('_')]
            for method in controller_methods:
                setattr(self, method[0], method[1])
            if not self.id:
                self.value = self.controller.default_value

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

        dirty_fields = self.get_dirty_fields(check_relationship=True)

        if self.pk:
            actor = get_current_user()
            action_performed = False
            if 'value' in dirty_fields:
                ComponentHistory.objects.create(
                    component=self, type='value', value=self.value,
                    user=actor
                )
                action.send(
                    actor, target=self, verb="value change",
                    instance_id=self.zone.instance.id,
                    action_type='comp_value', value=self.value
                )
                action_performed = True
                self.last_change = timezone.now()
            if 'arm_status' in dirty_fields:
                ComponentHistory.objects.create(
                    component=self, type='security',
                    value=self.arm_status, user=actor
                )
                action.send(
                    actor, target=self, verb="security event",
                    instance_id=self.zone.instance.id,
                    action_type='security', value=self.value
                )
                action_performed = True
                self.last_change = timezone.now()
            if action_performed:
                actor.last_action = timezone.now()
                actor.save()

            modifying_fields = (
                'name', 'icon', 'zone', 'category', 'config', 'meta',
                'value_units', 'slaves', 'show_in_app', 'alarm_category'
            )
            if any(f in dirty_fields for f in modifying_fields):
                self.last_modified = timezone.now()

        obj = super().save(*args, **kwargs)

        return obj

    def arm(self):
        # supports this method override in controller class
        if not self._controller_initiated:
            self._controller_initiated = True
            self.prepare_controller()
            return self.arm()
        self.refresh_from_db()
        if self.alarm_category:
            self.arm_status = 'pending-arm'
            self.save()

    def disarm(self):
        # supports this method override in controller class
        if not self._controller_initiated:
            self._controller_initiated = True
            self.prepare_controller()
            return self.disarm()
        self.refresh_from_db()
        self.arm_status = 'disarmed'
        self.save()

    def is_in_alarm(self):
        # supports this method override in controller class
        if not self._controller_initiated:
            self._controller_initiated = True
            self.prepare_controller()
            return self.is_in_alarm()
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

