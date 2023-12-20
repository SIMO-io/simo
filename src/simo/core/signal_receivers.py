import datetime
from django.db import transaction
from django.db.models.signals import post_save, pre_delete, post_delete
from django.dispatch import receiver
from django.utils import timezone
from .models import (
    Icon, Instance, Category, Zone, Gateway, Component, ComponentHistory
)


@receiver(post_save)
def post_save_management_events(sender, instance, created, **kwargs):
    from simo.users.utils import get_system_user
    if type(instance) not in (
        Icon, Category, Zone, Component, Gateway
    ):
        return
    from .events import ObjectManagementEvent
    dirty_fields = instance.get_dirty_fields()
    for ignore_field in ('change_init_by', 'change_init_date', 'change_init_to'):
        dirty_fields.pop(ignore_field, None)

    def post_update():
        if created:
            ObjectManagementEvent(instance, 'added').publish()
        elif dirty_fields:
            try:
                # sometimes crashes with gateway runners.
                ObjectManagementEvent(
                    instance, 'changed', dirty_fields=dirty_fields
                ).publish()
            except:
                pass

            if isinstance(instance, Component):
                for master in instance.masters.all():
                    try:
                        # sometimes crashes with gateway runners.
                        ObjectManagementEvent(
                            master, 'changed', slave_id=instance.id
                        ).publish()
                    except:
                        pass
    transaction.on_commit(post_update)


@receiver(post_delete)
def post_delete_management_event(sender, instance, *args, **kwargs):
    if type(instance) not in (Icon, Category, Zone, Component):
        return
    from .events import ObjectManagementEvent
    ObjectManagementEvent(instance, 'removed').publish()


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


@receiver(post_save, sender=Component)
def comp_post_save(sender, instance, created, **kwargs):

    state_changes = {}
    if not created:
        for field_name in ('value', 'arm_status'):
            if instance.tracker.has_changed(field_name):
                state_changes[field_name] = {
                    'old': instance.tracker.previous(field_name),
                    'new': getattr(instance, field_name)
                }

    def post_comp_update():
        if state_changes:
            from .events import Event
            Event(instance, state_changes).publish()

    transaction.on_commit(post_comp_update)


@receiver(post_save, sender=Instance)
def post_instance_save(sender, instance, created, **kwargs):
    if created:
        from simo.users.models import PermissionsRole
        PermissionsRole.objects.create(
            is_superuser=True, name='Admin'
        )
        PermissionsRole.objects.create(
            instance=instance, name='Owner', can_manage_users=True,
        )
        PermissionsRole.objects.create(
            name='User', can_manage_users=False, is_default=True
        )
