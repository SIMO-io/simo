import datetime
import requests
from django.db import transaction
from django.db import models
from django.db.models.signals import post_save, pre_delete, post_delete
from django.dispatch import receiver
from django.utils import timezone
from dirtyfields import DirtyFieldsMixin
from simo.core.models import Instance, Component
from simo.core.utils.helpers import get_random_string
from simo.core.events import ObjectCommand
from simo.conf import dynamic_settings
from .utils import get_gpio_pins_choices
from .ble import BLE_DEVICE_TYPE_GOVEE_MULTISENSOR


legacy_colonel_pins_map = {
    1: "R1", 2: "R2", 3: "R3", 4: "R4",
    5: "I1", 6: "I2", 7: "IO3", 8: "IO4",
    9: "IO5", 10: "IO6", 11: "IO7", 12: "IO8",
    13: "IO9", 14: "IO10", 15: "IO11|SCL", 16: "IO12|SDA"
}
legacy_colonel_pins_choices = [(None, '---------')] + [
    (key, val) for key, val in legacy_colonel_pins_map.items()
]


def get_new_secret():
    return get_random_string(12)


class InstanceOptions(models.Model):
    instance = models.OneToOneField(
        Instance, on_delete=models.CASCADE, related_name='fleet_options'
    )
    secret_key = models.CharField(max_length=20, default=get_new_secret)


@receiver(post_save, sender=Instance)
def create_instance_options(sender, instance, *args, **kwargs):
    InstanceOptions.objects.get_or_create(instance=instance)


class Colonel(DirtyFieldsMixin, models.Model):
    instance = models.ForeignKey(
        'core.Instance', on_delete=models.CASCADE, related_name='colonels',
        null=True,
    )
    uid = models.CharField(
        max_length=100, db_index=True, editable=False, unique=True,
    )
    name = models.CharField(max_length=100, blank=True)
    type = models.CharField(
        max_length=20, default='wESP32',
        choices=(
            ('wESP32', 'wESP32'), ('4-relays', '4 Relays'),
            ('ample-wall', "Ample Wall")
        )
    )
    firmware_version = models.CharField(
        max_length=50, editable=False, null=True
    )
    minor_upgrade_available = models.CharField(
        max_length=50, editable=False, null=True
    )
    major_upgrade_available = models.CharField(
        max_length=50, editable=False, null=True
    )
    firmware_auto_update = models.BooleanField(
        default=False,
        help_text="Keeps automatically up to date with minor and patch updates. "
                  "Major upgrade requires manual upgrade initiation"
    )
    socket_connected = models.BooleanField(default=False, db_index=True)
    ble_enabled = models.BooleanField('BLE enabled', default=False)
    last_seen = models.DateTimeField(null=True, editable=False, db_index=True)
    enabled = models.BooleanField(default=False)

    components = models.ManyToManyField(Component, editable=False)
    occupied_pins = models.JSONField(default=dict, blank=True)

    logs_stream = models.BooleanField(
        default=False, help_text="Might cause unnecessary overhead. "
                                 "Better to leave this off if things are running smoothly."
    )
    pwm_frequency = models.IntegerField(default=0, choices=(
        (0, "3kHz"), (1, "22kHz")
    ), help_text="Affects Ample Wall dimmer PWM output (dimmer) frequency")

    is_authorized = models.BooleanField(default=False, help_text="Temporrary field")

    def __str__(self):
        return self.name if self.name else self.uid

    def save(self, *args, **kwargs):
        if 'socket_connected' in self.get_dirty_fields() and self.pk:
            for comp in self.components.all():
                comp.alive = self.is_connected
                comp.save()
        is_new = self.pk is None

        if self.minor_upgrade_available and self.firmware_version == self.minor_upgrade_available:
            self.minor_upgrade_available = None
        if self.major_upgrade_available and self.firmware_version == self.major_upgrade_available:
            self.major_upgrade_available = None

        obj = super().save(*args, **kwargs)
        if is_new and self.type == 'ample-wall':
            I2CInterface.objects.create(
                colonel=self, name="Main", no=0, scl_pin=4, sda_pin=15,
                freq=100000
            )
        return obj

    @property
    def is_connected(self):
        if not self.socket_connected:
            return False
        if not self.last_seen:
            return False
        return self.last_seen > timezone.now() - datetime.timedelta(seconds=30)

    def newer_firmware_available(self):
        updates = []
        if self.major_upgrade_available:
            updates.append(self.major_upgrade_available)
        if self.minor_upgrade_available:
            updates.append(self.minor_upgrade_available)
        return ', '.join(updates)

    def check_for_upgrade(self):
        resp = requests.get(
            'https://simo.io/fleet/get-latest-version-available/', params={
                'current': self.firmware_version,
                'type': self.type,
                'instance_uid': self.instance.uid
            }
        )
        if resp.status_code != 200:
            print("Bad resonse! \n", resp.content)
            return
        self.minor_upgrade_available = resp.json().get('minor')
        self.major_upgrade_available = resp.json().get('major')
        self.save()
        return resp.json()

    def update_firmware(self, to_version):
        ObjectCommand(
            self, **{'command': 'update_firmware', 'to_version': to_version}
        ).publish()

    def restart(self):
        ObjectCommand(self, **{'command': 'restart'}).publish()

    def update_config(self):
        ObjectCommand(
            self, **{'command': 'update_config'}
        ).publish()

    def rebuild_occupied_pins(self):
        self.occupied_pins = {}
        for component in self.components.all():
            try:
                pins = component.controller._get_occupied_pins()
            except:
                pins = []
            for pin in pins:
                self.occupied_pins[pin] = component.id

        for i2c_interface in self.i2c_interfaces.all():
            self.occupied_pins[i2c_interface.scl_pin] = 'scl_%d' % i2c_interface.no
            self.occupied_pins[i2c_interface.sda_pin] = 'sda_%d' % i2c_interface.no

    def move_to(self, other_colonel):
        other_colonel.refresh_from_db()
        assert list(other_colonel.components.all()) == [], \
               "Other colonel must be completely empty!"

        for component in self.components.all():
            component.config['colonel'] = other_colonel.id
            component.save()
            self.components.remove(component)
            other_colonel.add(component)

        other_colonel.i2c_interfaces.all().delete()
        self.i2c_interfaces.all().update(colonel=other_colonel)

        self.rebuild_occupied_pins()
        self.save()

        other_colonel.rebuild_occupied_pins()
        other_colonel.save()

        self.update_config()
        other_colonel.update_config()



@receiver(pre_delete, sender=Component)
def post_component_delete(sender, instance, *args, **kwargs):
    if not instance.controller_uid.startswith('simo.fleet'):
        return

    affected_colonels = list(Colonel.objects.filter(components=instance))

    def update_colonel():
        for colonel in affected_colonels:
            print("Rebuild occupied pins for :", colonel)
            colonel.rebuild_occupied_pins()
            colonel.save()
            colonel.restart()

    transaction.on_commit(update_colonel)


i2c_interface_no_choices = (
    (0, "0 - Main"), (1, "1 - Secondary"),
    (2, "2 - Software"), (3, "3 - Software")
)


class I2CInterface(models.Model):
    colonel = models.ForeignKey(
        Colonel, on_delete=models.CASCADE, related_name='i2c_interfaces'
    )
    name = models.CharField(max_length=50)
    no = models.IntegerField(
        default=0, choices=i2c_interface_no_choices
    )
    scl_pin = models.IntegerField(default=4, choices=get_gpio_pins_choices())
    sda_pin = models.IntegerField(default=15, choices=get_gpio_pins_choices())
    freq = models.IntegerField(
        default=100000, help_text="100000 - is a good middle point!"
    )

    class Meta:
        unique_together = 'colonel', 'no'

    def __str__(self):
        return self.name


@receiver(post_delete, sender=I2CInterface)
def post_i2c_interface_delete(sender, instance, *args, **kwargs):

    def update_colonel():
        try:
            instance.colonel.rebuild_occupied_pins()
            instance.colonel.save()
        except Colonel.DoesNotExist: # deleting colonel
            pass
    transaction.on_commit(update_colonel)


@receiver(post_save, sender=I2CInterface)
def post_i2c_interface_delete(sender, instance, *args, **kwargs):

    def update_colonel():
        instance.colonel.rebuild_occupied_pins()
        instance.colonel.save()
    transaction.on_commit(update_colonel)


# class BLEDevice(models.Model):
#     mac = models.CharField(max_length=50, unique=True)
#     name = models.CharField(max_length=50)
#     addr = models.BinaryField(max_length=50)
#     type = models.PositiveIntegerField(default=0, choices=(
#         (0, "Unknown"),
#         (BLE_DEVICE_TYPE_GOVEE_MULTISENSOR, "GOVEE Climate sensor")
#     ))
#     last_seen = models.DateTimeField(auto_now_add=True)
#     component = models.ForeignKey(
#         Component, null=True, blank=True, on_delete=models.SET_NULL,
#         help_text='Only for tracking if it is already used as a component'
#     )
#     colonels = models.ManyToManyField(
#         Colonel, through='ColonelBLEDevice', related_name='ble_devices'
#     )
#
#     def __str__(self):
#         return '%s (%s)' % (self.name, self.mac)
#
#
# class ColonelBLEDevice(models.Model):
#     colonel = models.ForeignKey(Colonel, on_delete=models.CASCADE)
#     device = models.ForeignKey(BLEDevice, on_delete=models.CASCADE)
#     last_seen = models.DateTimeField(auto_now_add=True)
#     data = JSONField(default={})
#
#     def save(self, *args, **kwargs):
#         obj = super().save(*args, **kwargs)
#         self.device.last_seen = self.last_seen
#         self.device.save()
#         return obj
