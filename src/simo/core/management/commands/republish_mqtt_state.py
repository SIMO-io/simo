from django.core.management.base import BaseCommand
from django.utils import timezone

from simo.core.events import ObjectChangeEvent
from simo.core.models import Instance, Zone, Category, Component
from simo.users.models import InstanceUser


class Command(BaseCommand):
    help = "Republish retained MQTT state for zones, categories, components, and instance users."

    def add_arguments(self, parser):
        parser.add_argument('--instance', type=int, help='Instance ID to republish (default: all)')

    def handle(self, *args, **options):
        instance_id = options.get('instance')
        instances = Instance.objects.filter(is_active=True)
        if instance_id:
            instances = instances.filter(id=instance_id)

        count = 0
        for inst in instances:
            # Zones
            for zone in Zone.objects.filter(instance=inst):
                ObjectChangeEvent(inst, zone, name=zone.name).publish()
                count += 1

            # Categories
            for cat in Category.objects.filter(instance=inst):
                ObjectChangeEvent(
                    inst, cat, name=cat.name, last_modified=cat.last_modified
                ).publish()
                count += 1

            # Components
            for comp in Component.objects.filter(zone__instance=inst):
                data = {
                    'value': comp.value,
                    'last_change': comp.last_change,
                    'arm_status': comp.arm_status,
                    'battery_level': comp.battery_level,
                    'alive': comp.alive,
                    'meta': comp.meta,
                }
                ObjectChangeEvent(inst, comp, **data).publish()
                count += 1

            # Instance users (presence and phone charging)
            for iu in InstanceUser.objects.filter(instance=inst, is_active=True):
                ObjectChangeEvent(
                    inst,
                    iu,
                    at_home=iu.at_home,
                    last_seen=iu.last_seen,
                    phone_on_charge=iu.phone_on_charge,
                ).publish()
                count += 1

        self.stdout.write(self.style.SUCCESS(f"Republished {count} retained messages."))

