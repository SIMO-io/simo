

def get_superuser_role():
    from .models import PermissionsRole
    admin_role, new = PermissionsRole.objects.get_or_create(
        is_superuser=True, instance=None,
        defaults={'name': 'Global Admin'}
    )
    return admin_role


def get_system_user():
    from .models import User
    system, new = User.objects.get_or_create(
        email='system@simo.io', defaults={
            'role': get_superuser_role(), 'name': "System"
        }
    )
    return system


def get_device_user():
    from .models import User, PermissionsRole
    user_role = PermissionsRole.objects.filter(
        is_superuser=False, instance=None, name='Global User'
    ).first()
    if not user_role:
        user_role = PermissionsRole.objects.create(
            is_superuser=False, instance=None, name='Global User'
        )
    device, new = User.objects.get_or_create(
        email='device@simo.io', defaults={
            'role': user_role, 'name': "Device"
        }
    )
    return device


def rebuild_authorized_keys():
    from .models import User
    try:
        with open('/root/.ssh/authorized_keys', 'w') as keys_file:
            for user in User.objects.filter(
                ssh_key__isnull=False, is_active=True
            ):
                if user.is_superuser:
                    keys_file.write(user.ssh_key + '\n')
    except:
        # Simply do not do this if this installation does not have root permissions.
        pass
