import sys
import traceback
import subprocess
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