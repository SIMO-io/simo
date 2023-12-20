#!/usr/bin/python3
# -*- coding: utf-8 -*-
import requests
import simo
import sys
import os
import subprocess

HUB_DIR = '/etc/SIMO/hub'


def perform_update():
    package_dir = os.path.dirname(
        os.path.dirname(os.path.abspath(simo.__file__)))
    proc = subprocess.Popen(
        ['/usr/bin/git', 'pull'], cwd=package_dir,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    out, err = proc.communicate()
    if proc.returncode:
        raise Exception(out.decode() + '\n' + err.decode())
    print(out.decode())

    if out.decode().startswith('Already up to date'):
        return

    proc = subprocess.Popen(
        ['pip', 'install', '-e', package_dir],
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


if __name__ == "__main__":
    if not os.path.exists('/etc/SIMO/_var/auto_update'):
        print("Auto updates are disabled")
    else:
        current = simo.__version__
        resp = requests.get(
            'https://simo.io/get-latest-hub-version/?current=%s' % current
        )
        if resp.status_code != 200:
            sys.exit("Bad response from simo.io")
        latest = resp.content.decode()
        if current != latest:
            print("Need to update!")
            perform_update()
        else:
            print("Already up to date. Version: %s" % latest)
