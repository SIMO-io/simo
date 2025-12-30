import sys
import math
import traceback
import subprocess
import datetime
import numpy as np
from contextvars import ContextVar
from django.core.cache import cache
from django.utils import timezone
from django.template.loader import render_to_string



def get_system_user():
    from .models import User
    system, new = User.objects.get_or_create(
        email='system@simo.io', defaults={
            'name': "System"
        }
    )
    return system


def get_device_user():
    from .models import User
    device, new = User.objects.get_or_create(
        email='device@simo.io', defaults={
            'name': "Device"
        }
    )
    return device


def get_ai_user():
    from .models import User
    device, new = User.objects.get_or_create(
        email='ai@simo.io', defaults={
            'name': "AI"
        }
    )
    return device


def get_script_user():
    from .models import User
    user, _new = User.objects.get_or_create(
        email='script@simo.io',
        defaults={
            'name': 'Script',
            'is_master': False,
        },
    )
    try:
        if user.has_usable_password():
            user.set_unusable_password()
            user.save(update_fields=['password'])
    except Exception:
        pass
    return user


def rebuild_authorized_keys():
    from .models import User
    try:
        with open('/root/.ssh/authorized_keys', 'w') as keys_file:
            for user in User.objects.filter(
                ssh_key__isnull=False, is_master=True
            ):
                has_roles = user.instance_roles.filter(
                    instance__is_active=True
                ).first()
                has_active_roles = user.instance_roles.filter(
                    instance__is_active=True, is_active=True
                ).first()
                # if master user has active roles on some instances
                # but no longer has a single active role on an instance
                # he is most probably has been disabled by the property owner
                # therefore he should no longer be able to ssh in to this hub!
                if has_roles and not has_active_roles:
                    continue
                keys_file.write(user.ssh_key + '\n')
    except:
        print(traceback.format_exc(), file=sys.stderr)
        pass


def update_mqtt_acls():
    from .models import User
    users = User.objects.all()
    with open('/etc/mosquitto/acls.conf', 'w') as f:
        f.write(
            render_to_string('conf/mosquitto_acls.conf', {'users': users})
        )
    subprocess.run(
        ['service', 'mosquitto', 'reload'], stdout=subprocess.PIPE
    )


_current_user: ContextVar = ContextVar('simo_current_user', default=None)


def introduce_user(user):
    """Set current user for the current request/task context.

    Returns a token that can be used with ``reset_user``.
    """
    return _current_user.set(user)


def reset_user(token):
    _current_user.reset(token)


def get_current_user():
    user = _current_user.get()
    if not user:
        user = get_system_user()
        _current_user.set(user)
    return user
