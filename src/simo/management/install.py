#!/usr/bin/env python

"""
This should be called after simo has just been installed.
It prepares and powers up SIMO.io hub.
However it is not guaranteed to be fully operational.
"""
import os, sys, json, subprocess, socket, shutil, traceback
import simo
from django.template import Context, Engine
from django.core.management.utils import get_random_secret_key



def install_dependencies():

    status = subprocess.call(
        'apt install postgresql libpq-dev postgresql-client '
        'postgresql-client-common python3-pip redis-server supervisor '
        'mosquitto libopenjp2-7 libtiff5 pkg-config libcairo2-dev '
        'libgirepository1.0-dev libcairo2 libudev-dev gdal-bin net-tools '
        'timeshift nginx postgis openvpn ffmpeg libsm6 libxext6 ssh keychain -y',
        shell=True
    )
    if status != 0:
        print("Unable install required packages.")
        return

    return True


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


def copy_template(to_directory='/etc/SIMO'):
    template_file_extensions = ['.py', '.conf']

    context = Context({
        'secret_key': get_random_secret_key(),
        'project_dir': to_directory,
        'base_dir': to_directory
    }, autoescape=False)
    template_dir = os.path.join(
        os.path.dirname(simo.__file__), 'management', '_hub_template'
    )
    prefix_length = len(template_dir) + 1
    for root, dirs, files in os.walk(template_dir):
        relative_dir = root[prefix_length:]
        target_dir = os.path.join(to_directory, relative_dir)
        os.makedirs(target_dir, exist_ok=True)
        for filename in files:
            if filename.endswith(('.pyo', '.pyc', '.py.class')):
                # Ignore some files as they cause various breakages.
                continue
            old_path = os.path.join(root, filename)
            new_path = os.path.join(target_dir, filename)
            os.makedirs(target_dir, exist_ok=True)
            fn, file_extension = os.path.splitext(new_path)
            if file_extension in template_file_extensions:
                with open(old_path, encoding='utf-8') as template_file:
                    content = template_file.read()
                template = Engine().from_string(content)
                content = template.render(context)
                with open(new_path, 'w', encoding='utf-8') as new_file:
                    new_file.write(content)
            else:
                shutil.copyfile(old_path, new_path)
            shutil.copymode(old_path, new_path)
        for dirname in dirs[:]:
            if dirname.startswith('.') or dirname == '__pycache__':
                dirs.remove(dirname)
            else:
                os.makedirs(os.path.join(root, dirname), exist_ok=True)

    manage_py_path = os.path.join(to_directory, 'hub', 'manage.py')
    st = os.stat(manage_py_path)
    os.chmod(manage_py_path, st.st_mode | 0o111)


def install():
    # this must be performed on a host machine before simo could be installed.
    #
    # apt install python3-pip libpq-dev python3-dev -y

    simo_directory = '/etc/SIMO'
    installed_flag_file_path = os.path.join(simo_directory, 'is_installed.json')
    HUB_DIR = os.path.join(simo_directory, 'hub')

    if os.path.exists(installed_flag_file_path):
        print("SIMO.io hub is already installed. ")
        print(f"Please delete {installed_flag_file_path} file manually if you want to force this.")
        return

    step = 1
    print(f"{step}.___________Install dependencies__________________")
    status = subprocess.call(
        'apt-add-repository ppa:mosquitto-dev/mosquitto-ppa -y', shell=True
    )
    if status != 0:
        print("Unable to add mosquitto-dev dependency")
        print("Installation failed!")
        return

    status = subprocess.call('apt-get update -y', shell=True)
    if status != 0:
        print("Unable to apt-update")
        print("Installation failed!")
        return
    success = install_dependencies()
    if not success:
        print("Installation failed!")
        return

    step += 1
    print(f"{step}.___________Copy default template__________________")

    shutil.rmtree(simo_directory, ignore_errors=True)
    try:
        copy_template(simo_directory)
    except Exception as e:
        print(traceback.format_exc(), file=sys.stderr)
        shutil.rmtree(simo_directory, ignore_errors=True)
        return

    step += 1
    print(f"{step}.___________Create database__________________")
    subprocess.call(
        'sudo -u postgres createuser -s -i -d -r -l -w root',
        shell=True
    )
    subprocess.call('createdb SIMO', shell=True)

    step += 1
    print(f"{step}.___________Apply migrations__________________")

    proc = subprocess.Popen(
        [os.path.join(HUB_DIR, 'manage.py'), 'migrate'],
        cwd=HUB_DIR,
        stderr=subprocess.PIPE
    )
    out, err = proc.communicate()
    if proc.returncode:
        raise Exception(err.decode())

    step += 1
    print(f"{step}.___________Collect statics__________________")
    proc = subprocess.Popen(
        [os.path.join(HUB_DIR, 'manage.py'), 'collectstatic',
         '--noinput'],
        cwd=HUB_DIR, stderr=subprocess.PIPE
    )
    out, err = proc.communicate()
    if proc.returncode:
        raise Exception(err.decode())

    step += 1
    print(f"{step}.___________Configure supervisor__________________")

    try:
        os.remove('/etc/supervisor/conf.d/SIMO.conf')
    except:
        pass
    os.symlink(
        f'{simo_directory}/hub/supervisor.conf',
        '/etc/supervisor/conf.d/SIMO.conf'
    )
    os.makedirs('/var/log/simo')
    status = subprocess.call(['supervisorctl', 'update', 'all'])
    if status != 0:
        sys.exit("INSTALLATION FAILED! Unable to start supervisord")


    step += 1
    print("%d._____________ Configure NGINX _________________________" % step)

    try:
        os.remove('/etc/nginx/sites-enabled/default')
    except:
        pass

    os.symlink(
        '/etc/SIMO/hub/nginx.conf', '/etc/nginx/sites-enabled/SIMO'
    )

    try:
        os.remove('/etc/ssl/private/localhost.key')
    except:
        pass
    try:
        os.remove('/etc/ssl/certs/localhost.crt')
    except:
        pass

    status = subprocess.call([
        'openssl', 'req', '-x509', '-nodes', '-days', '36500',
        '-newkey', 'rsa:2048',
        '-subj', '/C=US/ST=Denial/L=Springfield/O=Dis/CN=simo.io',
        '-keyout', '/etc/ssl/private/localhost.key',
        '-out', '/etc/ssl/certs/localhost.crt'
    ])
    if status != 0:
        sys.exit(
            "INSTALLATION FAILED! Unable to prepare self signed certificate.")

    status = subprocess.call(['service', 'nginx', 'reload'])
    if status != 0:
        sys.exit("INSTALLATION FAILED! Something is wrong witn NGINX conf.")

    step += 1
    print("%d._____________ Configure SSH and Firewall_____________" % step)
    new_ssh_conf = ''
    with open('/etc/ssh/sshd_config', 'r') as ssh_conf:
        line = ssh_conf.readline()
        while line:
            if line.startswith('PasswordAuthentication'):
                line.replace(' yes', ' no')
            new_ssh_conf += line

            line = ssh_conf.readline()
    with open('/etc/ssh/sshd_config', 'w') as ssh_conf:
        ssh_conf.write(new_ssh_conf)

    status = subprocess.call(['service', 'ssh', 'restart'])
    if status != 0:
        sys.exit("INSTALLATION FAILED! Unable to restart SSH")

    stats = []
    stats.append(subprocess.call(['ufw', 'allow', 'ssh']))
    stats.append(subprocess.call(['ufw', 'allow', 'http']))
    stats.append(subprocess.call(['ufw', 'allow', 'https']))
    stats.append(subprocess.call(['ufw', 'allow', '1194']))
    stats.append(subprocess.call(['ufw', 'allow', '1883']))
    if any(stats):
        sys.exit("INSTALLATION FAILED! Unable to update UFW rules")

    status = subprocess.call('echo y | ufw enable', shell=True)
    if status != 0:
        sys.exit("INSTALLATION FAILED! Unable to enable UFW")


    step += 1
    print("%d.__________ CONFIGURE TIMESHIFT _____________________" % step)

    default_timeshift_file_path = '/etc/timeshift/default.json'
    if not os.path.exists(default_timeshift_file_path):
        default_timeshift_file_path = '/etc/timeshift/timeshift.json'
    if not os.path.exists(default_timeshift_file_path):
        default_timeshift_file_path = '/etc/default/timeshift.json'

    if not os.path.exists(default_timeshift_file_path):
        print("Unable to find default TimeShift config! Skip TimeShift configuration.")

    else:

        with open(default_timeshift_file_path, 'r') as conf_f:
            timeshift_conf = json.loads(conf_f.read())

        timeshift_conf['backup_device_uuid'] = subprocess.check_output(
            "lsblk -no UUID $(df -P /etc/SIMO/hub/settings.py | awk 'END{print $1}')",
            shell=True
        ).decode()[:-1]
        timeshift_conf['schedule_monthly'] = "true"
        timeshift_conf['schedule_weekly'] = "true"
        timeshift_conf['schedule_daily'] = "true"
        timeshift_conf['exclude'] = []

        # Must be copied to /etc/timeshift/timeshift.json to work
        with open('/etc/timeshift/timeshift.json', 'w') as conf_f:
            conf_f.write(json.dumps(timeshift_conf))

        # status = subprocess.call([
        #     '/usr/bin/timeshift', '--create',
        #     '--comments', '"Initial backup"', '--tags', 'M'
        # ])
        # if status != 0:
        #     print("Unable to start TimeShift")


    step += 1
    print("%d.__________ PUT UP INSTALL COMPLETE FLAG! _____________________" % step)

    with open(installed_flag_file_path, 'w') as f:
        f.write(json.dumps(True))

    print("--------------------------------------------------------------")
    print("DONE!")
    print("Your SIMO.io Hub is Up and running at: https://%s/" % get_ip())


if __name__ == "__main__":
    sys.exit(install())