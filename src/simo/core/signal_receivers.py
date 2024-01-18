import datetime
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Instance, Gateway, Component


@receiver(post_save, sender=Component)
def post_save_change_events(sender, instance, created, **kwargs):
    from .events import ObjectChangeEvent
    dirty_fields = instance.get_dirty_fields()
    for ignore_field in ('change_init_by', 'change_init_date', 'change_init_to'):
        dirty_fields.pop(ignore_field, None)

    def post_update():
        if dirty_fields:
            try:
                # sometimes crashes with gateway runners.
                ObjectChangeEvent(
                    instance.component.zone.instance, instance,
                    dirty_fields=dirty_fields
                ).publish()
            except:
                pass

            for master in instance.masters.all():
                try:
                    # sometimes crashes with gateway runners.
                    ObjectChangeEvent(
                        master.component.zone.instance,
                        master, slave_id=instance.id
                    ).publish()
                except:
                    pass

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
