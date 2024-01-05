import sys
import traceback


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
                ssh_key__isnull=False
            ):
                if user.is_active and user.is_master:
                    keys_file.write(user.ssh_key + '\n')
    except:
        print(traceback.format_exc(), file=sys.stderr)
        pass
