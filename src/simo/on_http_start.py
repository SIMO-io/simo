import os
import pwd
import grp
import subprocess
from django.conf import settings
from django.template.loader import render_to_string


def prepare_mosquitto():
    if os.geteuid() != 0:
        return

    from simo.users.models import User

    users_file = '/etc/mosquitto/mosquitto_users'
    if not os.path.exists(users_file):
        with open(users_file, 'w') as f:
            f.write('')

        uid = pwd.getpwnam("mosquitto").pw_uid
        gid = grp.getgrnam("mosquitto").gr_gid
        os.chown(users_file, uid, gid)
        os.chmod(users_file, 0o640)

        acls_file = '/etc/mosquitto/acls.conf'
        with open(acls_file, 'w') as f:
            f.write('')

        uid = pwd.getpwnam("mosquitto").pw_uid
        gid = grp.getgrnam("mosquitto").gr_gid
        os.chown(acls_file, uid, gid)
        os.chmod(acls_file, 0o640)

    ps = subprocess.Popen(
        ['mosquitto_passwd /etc/mosquitto/mosquitto_users root'],
        shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    ps.communicate(f"{settings.SECRET_KEY}\n{settings.SECRET_KEY}".encode())

    for user in User.objects.all():
        user.update_mqtt_secret(reload=False)

    from simo.users.utils import update_mqtt_acls

    update_mqtt_acls()

    if not os.path.exists('/etc/mosquitto/conf.d/simo.conf'):
        with open('/etc/mosquitto/conf.d/simo.conf', 'w') as f:
            f.write(render_to_string('conf/mosquitto.conf'))

    subprocess.run(
        ['service', 'mosquitto', 'reload'], stdout=subprocess.PIPE
    )

prepare_mosquitto()


def update_auto_update():
    import simo
    auto_update_file_path = os.path.join(
        os.path.dirname(simo.__file__), 'auto_update.py'
    )
    st = os.stat(auto_update_file_path)
    os.chmod(auto_update_file_path, st.st_mode | 0o111)

    executable_path = '/usr/local/bin/simo-auto-update'
    if os.geteuid() == 0:
        # We are running as root!
        if not os.path.islink(executable_path):
            # There is no symbolic link yet made for auto updates.
            # Let's make it!
            os.symlink(auto_update_file_path, executable_path)
            auto_update_cron = f'0 * * * * {executable_path} \n'
            cron_out = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE)
            cron_out.communicate(input=str.encode(auto_update_cron))


update_auto_update()