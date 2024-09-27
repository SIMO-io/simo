import requests
import sys
import os
import subprocess
import pkg_resources


HUB_DIR = '/etc/SIMO/hub'


def perform_update():

    proc = subprocess.Popen(
        ['pip', 'install', 'simo', '--upgrade'],
        cwd=HUB_DIR, stderr=subprocess.PIPE
    )
    out, err = proc.communicate()
    if proc.returncode:
        raise Exception(err.decode())

    proc = subprocess.Popen(
        [os.path.join(HUB_DIR, 'manage.py'), 'migrate'],
        cwd=HUB_DIR,
        stderr=subprocess.PIPE
    )
    out, err = proc.communicate()
    if proc.returncode:
        raise Exception(err.decode())

    proc = subprocess.Popen(
        [os.path.join(HUB_DIR, 'manage.py'), 'collectstatic',
         '--noinput'],
        cwd=HUB_DIR, stderr=subprocess.PIPE
    )
    out, err = proc.communicate()
    if proc.returncode:
        raise Exception(err.decode())

    subprocess.run(['redis-cli', 'flushall'])
    proc = subprocess.Popen(
        ['supervisorctl', 'restart', 'all'],
        cwd=HUB_DIR, stderr=subprocess.PIPE
    )
    out, err = proc.communicate()
    if proc.returncode:
        raise Exception(err.decode())

    print("Update completed!")


def maybe_update():
    if not os.path.exists('/etc/SIMO/_var/auto_update'):
        print("Auto updates are disabled")
    else:
        current = pkg_resources.get_distribution('simo').version
        resp = requests.get("https://pypi.org/pypi/simo/json")
        if resp.status_code != 200:
            sys.exit("Bad response from PyPi")
        latest = resp.json()['info']['version']
        if current != latest:
            print(f"Need to update! We are on {current} but {latest} is available!")
            print("Let's GO!")
            perform_update()
        else:
            print("Already up to date. Version: %s" % latest)