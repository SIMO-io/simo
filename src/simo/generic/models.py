import time
import sys
import traceback
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from simo.core.models import Component
from simo.users.models import InstanceUser
from .tasks import (
    notify_users_on_alarm_group_breach,
    fire_breach_events
)


@receiver(post_save, sender=Component)
def handle_alarm_groups(sender, instance, *args, **kwargs):
    if not instance.alarm_category:
        return
    if hasattr(instance, 'do_not_update_alarm_group'):
        return
    dirty_fields = instance.get_dirty_fields()
    if 'arm_status' not in dirty_fields:
        return

    from .controllers import AlarmGroup

    for ag in Component.objects.filter(
        controller_uid=AlarmGroup.uid,
        config__components__contains=instance.id,
    ).exclude(value='disarmed'):
        stats = {
            'disarmed': 0, 'pending-arm': 0, 'armed': 0, 'breached': 0
        }
        stats[instance.arm_status] += 1
        for slave in Component.objects.filter(
            pk__in=ag.config['components'],
        ).exclude(pk=instance.pk):
            stats[slave.arm_status] += 1

        print(f"STATS OF {ag} are: {stats}")
        ag.config['stats'] = stats


        if stats['disarmed'] == len(ag.config['components']):
            alarm_group_value = 'disarmed'
        elif stats['armed'] == len(ag.config['components']):
            alarm_group_value = 'armed'
        elif stats['breached']:
            alarm_group_value = 'breached'
        else:
            alarm_group_value = 'pending-arm'

        print(f"{ag} value: {alarm_group_value}")

        if alarm_group_value == 'breached' and instance.arm_status == 'breached':
            if ag.value != 'breached':
                ag.meta['breach_times'] = [time.time()]
            else:
                ag.meta['breach_times'].append(time.time())

        ag.save(update_fields=['meta', 'config'])
        ag.controller.set(alarm_group_value)

        if alarm_group_value == 'breached' and instance.arm_status == 'breached':
            for event in ag.config['breach_events']:
                if event['uid'] in ag.meta.get('events_triggered', []):
                    continue
                threshold = event.get('threshold', 1)
                if len(ag.meta['breach_times']) < threshold:
                    continue
                fire_breach_events.apply_async(
                    args=[ag.id], countdown=event['delay']
                )


@receiver(pre_save, sender=Component)
def manage_alarm_groups(sender, instance, *args, **kwargs):
    from .controllers import AlarmGroup

    if instance.controller_uid != AlarmGroup.uid:
        return

    if 'value' not in instance.get_dirty_fields():
        return

    if instance.value == 'breached':
        instance.meta['events_triggered'] = []

        if instance.config.get('notify_on_breach') is not None:
            notify_users_on_alarm_group_breach.apply_async(
                args=[instance.id],
                countdown=instance.config['notify_on_breach']
            )

    elif instance.get_dirty_fields()['value'] == 'breached' \
    and instance.value == 'disarmed':
        instance.meta['breach_start'] = None
        for event_uid in instance.meta.get('events_triggered', []):
            event = instance.controller.events_map.get(event_uid)
            if not event:
                continue
            if not event.get('disarm_action'):
                continue
            try:
                getattr(event['component'], event['disarm_action'])()
            except Exception:
                print(traceback.format_exc(), file=sys.stderr)


@receiver(post_delete, sender=Component)
def clear_alarm_group_config_on_component_delete(
    sender, instance, *args, **kwargs
):
    from .controllers import AlarmGroup

    for ag in Component.objects.filter(
        base_type=AlarmGroup.base_type,
        config__components__contains=instance.id
    ):
        ag.config['components'] = [
            id for id in ag.config.get('components', []) if id != instance.id
        ]
        ag.save(update_fields=['config'])


@receiver(post_save, sender=Component)
def bind_controlling_locks_to_alarm_groups(sender, instance, *args, **kwargs):
    if instance.base_type != 'lock':
        return
    if 'value' not in instance.get_dirty_fields():
        return

    from .controllers import AlarmGroup

    if instance.value == 'locked':
        for ag in Component.objects.filter(
            base_type=AlarmGroup.base_type,
            config__arming_locks__contains=instance.id
        ):
            if ag.config.get('arm_on_away') in (None, '', 'on_away'):
                ag.controller.arm()
                continue

            users_at_home = InstanceUser.objects.filter(
                instance=instance.instance, at_home=True
            ).exclude(is_active=False).exclude(id=instance.id).count()
            if users_at_home:
                continue
            if ag.config.get('arm_on_away') == 'on_away_and_locked':
                print(f"Nobody is at home, lock was locked. Arm {ag}!")
                ag.controller.arm()
                continue
            locked_states = [
                True if l['value'] == 'locked' else False
                for l in Component.objects.filter(
                    base_type='lock', id__in=ag.config.get('arming_locks', []),
                ).values('value')
            ]
            if all(locked_states):
                print(f"Nobody is at home, all locks are now locked. Arm {ag}!")
                ag.controller.arm()

    elif instance.value == 'unlocked':
        for ag in Component.objects.filter(
            base_type=AlarmGroup.base_type,
            config__arming_locks__contains=instance.id
        ):
            ag.controller.disarm()


@receiver(post_save, sender=InstanceUser)
def bind_alarm_groups(sender, instance, created, *args, **kwargs):
    if created:
        return
    if instance.at_home:
        return
    if 'at_home' not in instance.get_dirty_fields():
        return
    users_at_home = InstanceUser.objects.filter(
        instance=instance.instance, at_home=True
    ).exclude(is_active=False).exclude(id=instance.id).count()
    if users_at_home:
        return

    from .controllers import AlarmGroup

    for ag in Component.objects.filter(
        zone__instance=instance.instance,
        base_type=AlarmGroup.base_type,
        config__arm_on_away__startswith='on_away_and_locked'
    ):
        locked_states = [
            True if l['value'] == 'locked' else False
            for l in Component.objects.filter(
                base_type='lock', id__in=ag.config.get('arming_locks', []),
            ).values('value')
        ]
        if not any(locked_states):
            print("Not a single lock is locked. Continue.")
            continue
        if ag.config['arm_on_away'] == 'on_away_and_locked':
            print(f"Everybody is away, single lock is locked, arm {ag}!")
            ag.controller.arm()
            continue
        if ag.config['arm_on_away'] == 'on_away_and_locked_all' \
        and all(locked_states):
            print(f"Everybody is away, all locks are locked, arm {ag}!")
            ag.controller.arm()
            continue