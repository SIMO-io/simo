import requests
import time
from django.db import transaction
from django.db import models
from django.db.models.signals import post_save, pre_delete, post_delete
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from dirtyfields import DirtyFieldsMixin
from simo.core.models import Instance, Gateway, Component
from simo.core.utils.helpers import get_random_string
from simo.core.events import GatewayObjectCommand
from .gateways import FleetGatewayHandler
from .managers import ColonelsManager, ColonelPinsManager, I2CInterfacesManager
from .utils import GPIO_PINS



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
        max_length=20, default='ample-wall',
        choices=(
            ('4-relays', "4 Relay"),
            ('ample-wall', "Ample Wall"),
            ('game-changer', "Game Changer"),
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
        default=False, help_text="ATENTION! Causes serious overhead and "
                                 "significantly degrades the lifespan of a chip "
                                 "due to a lot of writes to the memory. "                       
                                 "It also causes Colonel websocket to run out of memory "
                                 "and reset if a lot of data is being transmitted. "
                                 "Leave this off, unleess you know what you are doing!"
    )
    pwm_frequency = models.IntegerField(default=1, choices=(
        (0, "3kHz"), (1, "22kHz")
    ), help_text="Affects Ample Wall dimmer PWM output (dimmer) frequency")

    objects = ColonelsManager()

    def __str__(self):
        return self.name if self.name else self.uid

    def save(self, *args, **kwargs):
        if 'socket_connected' in self.get_dirty_fields() and self.pk:
            for comp in self.components.all():
                comp.alive = self.is_connected
                comp.save()

        if self.minor_upgrade_available and self.firmware_version == self.minor_upgrade_available:
            self.minor_upgrade_available = None
        if self.major_upgrade_available and self.firmware_version == self.major_upgrade_available:
            self.major_upgrade_available = None

        return super().save(*args, **kwargs)

    @property
    def is_connected(self):
        if not self.socket_connected:
            return False
        if not self.last_seen:
            return False
        return True

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
        for gateway in Gateway.objects.filter(type=FleetGatewayHandler.uid):
            GatewayObjectCommand(
                gateway, self,
                command='update_firmware', to_version=to_version
            ).publish()

    def restart(self):
        for gateway in Gateway.objects.filter(type=FleetGatewayHandler.uid):
            GatewayObjectCommand(
                gateway, self, command='restart'
            ).publish()

    def update_config(self):
        for gateway in Gateway.objects.filter(type=FleetGatewayHandler.uid):
            GatewayObjectCommand(
                gateway, self, command='update_config'
            ).publish()

    @transaction.atomic
    def rebuild_occupied_pins(self):
        for pin in ColonelPin.objects.filter(colonel=self):
            pin.occupied_by = None
            pin.save()

        for component in self.components.all():
            try:
                pins = component.controller._get_occupied_pins()
            except:
                pins = []
            for no in pins:
                pin, new = ColonelPin.objects.get_or_create(colonel=self, no=no)
                pin.occupied_by = component
                pin.save()

        for interface in self.i2c_interfaces.all():
            interface.sda_pin.occupied_by = interface
            interface.sda_pin.save()
            interface.scl_pin.occupied_by = interface
            interface.scl_pin.save()


    def move_to(self, other_colonel):
        self.restart()
        other_colonel.restart()
        time.sleep(1)
        self.uid = other_colonel.uid
        other_colonel.delete()
        self.save()


class ColonelPin(models.Model):
    colonel = models.ForeignKey(
        Colonel, related_name='pins', on_delete=models.CASCADE
    )
    no = models.PositiveIntegerField()
    label = models.CharField(db_index=True, max_length=200)
    input = models.BooleanField(default=False, db_index=True)
    output = models.BooleanField(default=False, db_index=True)
    capacitive = models.BooleanField(default=False, db_index=True)
    adc = models.BooleanField(default=False)
    native = models.BooleanField(default=True, db_index=True)
    default_pull = models.CharField(
        max_length=50, db_index=True, null=True, blank=True,
        choices=(('LOW', "LOW"), ("HIGH", "HIGH"))
    )
    note = models.CharField(max_length=100)
    occupied_by_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True
    )
    occupied_by_id = models.PositiveIntegerField(null=True)
    occupied_by = GenericForeignKey(
        "occupied_by_content_type", "occupied_by_id"
    )

    objects = ColonelPinsManager()

    class Meta:
        unique_together = 'colonel', 'no'
        indexes = [
            models.Index(
                fields=["occupied_by_content_type", "occupied_by_id"]
            ),
        ]
    def __str__(self):
        if not self.label:
            # Might be created via migration...
            self.save()
        return self.label

    def save(self, *args, **kwargs):
        if self.native:
            self.label = f'GPIO{self.no}'
        else:
            no = self.no - 100
            self.label = f'IO{no}'
        if self.note:
            self.label += ' | %s' % self.note
        return super().save(*args, **kwargs)


@receiver(post_save, sender=Colonel)
def after_colonel_save(sender, instance, created, *args, **kwargs):
    if created:
        for no, data in GPIO_PINS.get(instance.type).items():
            ColonelPin.objects.get_or_create(
                colonel=instance, no=no,
                input=data.get('input'), output=data.get('output'),
                capacitive=data.get('capacitive'), adc=data.get('adc'),
                native=data.get('native'), note=data.get('note')
            )
        if instance.type in ('ample-wall', 'game-changer'):
            I2CInterface.objects.create(
                colonel=instance, name='Main', no=0,
                scl_pin=ColonelPin.objects.get(colonel=instance, no=4),
                sda_pin=ColonelPin.objects.get(colonel=instance, no=15),
            )


@receiver(pre_delete, sender=Component)
def post_component_delete(sender, instance, *args, **kwargs):
    if not instance.controller_uid.startswith('simo.fleet'):
        return

    affected_colonels = list(Colonel.objects.filter(components=instance))

    def update_colonel():
        for colonel in affected_colonels:
            print("Rebuild occupied pins for :", colonel)
            colonel.rebuild_occupied_pins()
            colonel.update_config()

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
    scl_pin = models.ForeignKey(
        ColonelPin, on_delete=models.CASCADE, limit_choices_to={
            'native': True, 'output': True,
        },
        null=True, related_name='i2c_scl'
    )
    sda_pin = models.ForeignKey(
        ColonelPin, on_delete=models.CASCADE, limit_choices_to={
            'native': True, 'output': True,
        },
        null=True, related_name='i2c_sda'
    )
    freq = models.IntegerField(
        default=100000, help_text="100000 - is a good middle point!"
    )

    objects = I2CInterfacesManager()

    class Meta:
        unique_together = 'colonel', 'no'

    def __str__(self):
        return self.name


@receiver(post_save, sender=I2CInterface)
def post_i2c_interface_delete(sender, instance, *args, **kwargs):
    with transaction.atomic():
        ct = ContentType.objects.get_for_model(instance)
        for pin in ColonelPin.objects.filter(
            occupied_by_content_type=ct,
            occupied_by_id=instance.id
        ):
            pin.occupied_by_content_type = None
            pin.occupied_by_content_id = None
            pin.save()
        instance.scl_pin.occupied_by = instance
        instance.scl_pin.save()
        instance.sda_pin.occupied_by = instance
        instance.sda_pin.save()
