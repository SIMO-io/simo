import os
import shutil
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.conf import settings
from actstream import action
from simo.users.models import PermissionsRole
from .models import Instance, Gateway, Component, Icon, Zone, Category


@receiver(post_save, sender=Instance)
def create_instance_defaults(sender, instance, created, **kwargs):
    if not created:
        return

    from simo.users.middleware import get_current_user
    actor = get_current_user()
    action.send(
        actor, target=instance, verb="instance created",
        instance_id=instance.id,
        action_type='management_event'
    )

    # Create default zones

    for zone_name in (
        'Living Room', 'Kitchen', 'Bathroom', 'Porch', 'Garage', 'Yard', 'Other'
    ):
        Zone.objects.create(instance=instance, name=zone_name)

    core_dir_path = os.path.dirname(os.path.realpath(__file__))
    imgs_folder = os.path.join(
        core_dir_path, 'static/defaults/category_headers'
    )

    categories_media_dir = os.path.join(settings.MEDIA_ROOT, 'categories')
    if not os.path.exists(categories_media_dir):
        os.makedirs(categories_media_dir)

    # Create default categories

    for i, data in enumerate([
        ("All", 'star'), ("Climate", 'temperature-half'),
        ("Lights", 'lightbulb'), ("Security", 'eye'),
        ("Watering", 'faucet'), ("Other", 'flag-pennant')
    ]):
        shutil.copy(
            os.path.join(imgs_folder, "%s.jpg" % data[0].lower()),
            os.path.join(
                settings.MEDIA_ROOT, 'categories', "%s.jpg" % data[0].lower()
            )
        )
        Category.objects.create(
            instance=instance,
            name=data[0], icon=Icon.objects.get(slug=data[1]),
            all=i == 0, header_image=os.path.join(
                'categories', "%s.jpg" % data[0].lower()
            ), order=i + 10
        )

    # Create generic gateway and components

    generic, new = Gateway.objects.get_or_create(
        type='simo.generic.gateways.GenericGatewayHandler'
    )
    generic.start()
    dummy, new = Gateway.objects.get_or_create(
        type='simo.generic.gateways.DummyGatewayHandler'
    )
    dummy.start()
    weather_icon = Icon.objects.get(slug='cloud-bolt-sun')
    other_zone = Zone.objects.get(name='Other', instance=instance)
    climate_category = Category.objects.get(name='Climate', instance=instance)
    Component.objects.create(
        name='Weather', icon=weather_icon,
        zone=other_zone,
        category=climate_category,
        gateway=generic, base_type='weather-forecast',
        controller_uid='simo.generic.controllers.WeatherForecast',
        config={'is_main': True}
    )

    # Create default User permission roles

    PermissionsRole.objects.create(
        instance=instance, name="Admin", is_superuser=True
    )
    PermissionsRole.objects.create(
        instance=instance, name="Owner", is_owner=True, is_default=True
    )
    PermissionsRole.objects.create(
        instance=instance, name="Guest", is_owner=True
    )


@receiver(post_save, sender=Zone)
@receiver(post_save, sender=Category)
def post_save_actions_dispatcher(sender, instance, created, **kwargs):
    from simo.users.middleware import get_current_user
    actor = get_current_user()
    if created:
        verb = 'created'
    else:
        verb = 'modified'
    action.send(
        actor, target=instance, verb=verb,
        instance_id=instance.instance.id,
        action_type='management_event'
    )


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
