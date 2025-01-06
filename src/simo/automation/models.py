import time
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from simo.core.models import Component


@receiver(post_save, sender=Component)
def post_script_change(sender, instance, created, **kwargs):
    from .controllers import Script
    if not isinstance(instance.controller, Script):
        return

    if 'config' not in instance.get_dirty_fields():
        return

    def post_update():
        if instance.value == 'running':
            instance.controller.stop()
        if instance.config.get('autostart'):
            time.sleep(2)
            instance.controller.start()

    transaction.on_commit(post_update)


@receiver(post_delete, sender=Component)
def gateway_post_delete(sender, instance, *args, **kwargs):
    from .controllers import Script
    if not isinstance(instance.controller, Script):
        return
    instance.stop()