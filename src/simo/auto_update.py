#!/usr/bin/python3
# -*- coding: utf-8 -*-
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


if __name__ == "__main__":
    if not os.path.exists('/etc/SIMO/_var/auto_update'):
        print("Auto updates are disabled")
    else:
        current = pkg_resources.get_distribution('simo').version
        resp = requests.get("https://pypi.org/pypi/simo/json")
        if resp.status_code != 200:
            sys.exit("Bad response from PyPi")
        latest = list(resp.json()['releases'].keys())[-1]
        if current != latest:
            print("Need to update!")
            perform_update()
        else:
            print("Already up to date. Version: %s" % latest)
