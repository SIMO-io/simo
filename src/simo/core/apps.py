import os
import subprocess
from django.apps import AppConfig


class CoreAppConfig(AppConfig):
    name = 'simo.core'

    def ready(self):
        import simo
        auto_update_file_path = os.path.join(
            os.path.dirname(simo.__file__), 'auto_update.py'
        )
        st = os.stat(auto_update_file_path)
        os.chmod(auto_update_file_path, st.st_mode | 0o111)

        executable_path = '/usr/local/bin/simo-auto-update'
        if os.geteuid() == 0 and not os.path.exists(executable_path):
            # We are running as root and there is no symbolic link yet made
            # for auto updates.
            os.symlink(auto_update_file_path, executable_path)
            auto_update_cron = f'0 * * * * {executable_path} \n'
            cron_out = subprocess.Popen(['crontab', '-'], stdin=subprocess.PIPE)
            cron_out.communicate(input=str.encode(auto_update_cron))
