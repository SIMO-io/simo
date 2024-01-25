from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from .models import Instance, Gateway, Component


@receiver(post_save, sender=Component)
@receiver(post_save, sender=Gateway)
def post_save_change_events(sender, instance, created, **kwargs):
    target = instance
    from .events import ObjectChangeEvent
    dirty_fields = target.get_dirty_fields()
    for ignore_field in (
        'change_init_by', 'change_init_date', 'change_init_to', 'last_update'
    ):
        dirty_fields.pop(ignore_field, None)

    def post_update():
        if not dirty_fields:
            return

        if type(target) == Gateway:
            ObjectChangeEvent(
                None, target,
                dirty_fields=dirty_fields,
                timestamp=timezone.now().timestamp()
            ).publish()
        elif type(target) == Component:
            data = {}
            for field_name in (
                'value', 'last_change', 'arm_status',
                'battery_level', 'alive', 'meta'
            ):
                data[field_name] = getattr(target, field_name, None)
            ObjectChangeEvent(
                target.zone.instance, target,
                dirty_fields=dirty_fields,
                timestamp=timezone.now().timestamp(),
                **data
            ).publish()
            for master in target.masters.all():
                data = {}
                for field_name in (
                    'value', 'last_change', 'arm_status',
                    'battery_level', 'alive', 'meta'
                ):
                    data[field_name] = getattr(master, field_name, None)
                ObjectChangeEvent(
                    master.zone.instance,
                    master, slave_id=target.id,
                    timestamp=timezone.now().timestamp(),
                    **data
                ).publish()

    transaction.on_commit(post_update)


@receiver(post_save, sender=Gateway)
def gateway_post_save(sender, instance, created, *args, **kwargs):
    def start_gw():
        if created:
            gw = Gateway.objects.get(pk=instance.pk)
            gw.start()

    transaction.on_commit(start_gw)


@receiver(post_delete, sender=Gateway)
def gateway_post_delete(sender, instance, *args, **kwargs):
    instance.stop()


@receiver(post_save, sender=Instance)
def post_instance_save(sender, instance, created, **kwargs):
    if created:
        from simo.users.models import PermissionsRole
        PermissionsRole.objects.create(
            instance=instance, name='Owner', can_manage_users=True,
        )
        PermissionsRole.objects.create(
            instance=instance, name='User', can_manage_users=False, is_default=True
        )
