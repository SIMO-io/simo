import os
import pwd
import grp
import subprocess
from django.conf import settings
from django.template.loader import render_to_string
from django.apps import AppConfig


class CoreAppConfig(AppConfig):
    name = 'simo.users'

    def ready(self):
        if os.geteuid() != 0:
            return

        from .models import User
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
            shell=True, stdin=subprocess.PIPE,stdout=subprocess.PIPE
        )
        ps.communicate(f"{settings.SECRET_KEY}\n{settings.SECRET_KEY}".encode())

        for user in User.objects.all():
            user.update_mqtt_secret(reload=False)

        from .utils import update_mqtt_acls
        update_mqtt_acls()

        if not os.path.exists('/etc/mosquitto/conf.d/simo.conf'):
            with open('/etc/mosquitto/conf.d/simo.conf', 'w') as f:
                f.write(render_to_string('conf/mosquitto.conf'))

        subprocess.run(
            ['service', 'mosquitto', 'reload'], stdout=subprocess.PIPE
        )
