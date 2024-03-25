import time
import os
import io
import json
import base64
import datetime
import requests
import subprocess
import threading
import simo
import pkg_resources
from django.db.models import Q
from django.db import connection
from django.db import transaction
from django.template.loader import render_to_string
from easy_thumbnails.files import get_thumbnailer
from celeryc import celery_app
from django.utils import timezone
from django.conf import settings
from simo.conf import dynamic_settings
from simo.core.utils.helpers import get_self_ip
from .models import Instance, Component, ComponentHistory, HistoryAggregate
from .utils.helpers import get_random_string, is_update_available


def supervisor_restart():
    time.sleep(2)
    subprocess.run(['redis-cli', 'flushall'])
    subprocess.run(['supervisorctl', 'restart', 'all'])


def save_config(data):

    vpn_change = False
    if 'vpn_ca' in data:
        vpn_change = True
        try:
            with open('/etc/openvpn/client/simo_io.ca', 'w') as ca_f:
                ca_f.write(data['vpn_ca'])
        except:
            print("Unable to setup openvpn locally")

    if 'vpn_key' in data:
        vpn_change = True
        try:
            with open('/etc/openvpn/client/simo_io.key', 'w') as key_f:
                key_f.write(data['vpn_key'])
        except:
            print("Unable to setup openvpn locally")

    if 'vpn_crt' in data:
        vpn_change = True
        try:
            with open('/etc/openvpn/client/simo_io.crt', 'w') as crt_f:
                crt_f.write(data['vpn_crt'])
        except:
            print("Unable to setup openvpn locally")

    if 'vpn_ta' in data:
        vpn_change = True
        try:
            with open('/etc/openvpn/client/simo_io.ta', 'w') as ta_f:
                ta_f.write(data['vpn_ta'])
        except:
            print("Unable to setup openvpn locally")

    if 'router_address' in data:
        vpn_change = True
        try:
            with open('/etc/openvpn/client/simo_io.conf', 'w') as conf_f:
                conf_f.write(
                    render_to_string(
                        'core/openvpn_client.conf',
                        {'router_address': data['router_address']}
                    )
                )
        except:
            print("Unable to setup openvpn locally")

    def restart_openvpn():
        time.sleep(2)
        print("Restarting openvpn!")
        try:
            subprocess.run(
                ['/usr/bin/systemctl', 'enable',
                 'openvpn-client@simo_io.service']
            )
        except:
            pass
        try:
            subprocess.run(
                ['/usr/bin/systemctl', 'restart',
                 'openvpn-client@simo_io.service']
            )
        except:
            pass

    if vpn_change:
        threading.Thread(target=restart_openvpn).start()


@celery_app.task
def sync_with_remote():
    from simo.users.models import User

    instances = Instance.objects.all()
    if not instances:
        # No initial configuration yet
        return

    report_data = {
        'simo_version': pkg_resources.get_distribution('simo').version,
        'local_http': 'https://%s' % get_self_ip(),
        'hub_uid': dynamic_settings['core__hub_uid'],
        'hub_secret': dynamic_settings['core__hub_secret'],
        'instances': []
    }
    for instance in instances:
        instance_data = {
            'uid': instance.uid,
            'name': instance.name,
            'slug': instance.slug,
            'units_of_measure': instance.units_of_measure,
            'timezone': instance.timezone,
            # Security measure!
            # Users of this list only will be allowed to authenticate via SSO
            # and access your hub via mobile APP.
            'users': [],
        }

        for user in User.objects.filter(
            Q(roles__instance=instance) | Q(is_master=True)
        ).exclude(email__in=('system@simo.io', 'device@simo.io')):
            is_superuser = False
            user_role = user.get_role(instance)
            if user_role and user_role.is_superuser:
                is_superuser = True
            instance_data['users'].append({
                'email': user.email,
                'is_hub_master': user.is_master,
                'is_superuser': is_superuser,
                'device_token': user.primary_device_token
            })

        last_event = ComponentHistory.objects.filter(
            component__zone__instance=instance
        ).order_by('-date').first()
        if last_event:
            instance_data['last_event'] = last_event.date.timestamp()
        if instance.share_location:
            instance_data['location'] = instance.location
        if instance.cover_image and not instance.cover_image_synced:
            cover_imb_path = instance.cover_image.get_thumbnail(
                {'size': (880, 490), 'crop': True}
            ).path
            with open(cover_imb_path, 'rb') as img:
                instance_data['cover_image'] = base64.b64encode(
                    img.read()
                ).decode()
        report_data['instances'].append(instance_data)

    print("Sync UP with remote: ", json.dumps(report_data))

    response = requests.post('https://simo.io/hubs/sync/', json=report_data)
    if response.status_code != 200:
        print("Faled! Response code: ", response.status_code)
        return

    print("Responded with: ", json.dumps(response.json()))

    for instance in instances:
        instance.cover_image_synced = True
        instance.save()

    r_json = response.json()
    dynamic_settings['core__remote_http'] = r_json.get('hub_remote_http')
    if 'new_secret' in r_json:
        dynamic_settings['core__hub_secret'] = r_json['new_secret']

    if dynamic_settings['core__remote_conn_version'] < r_json['remote_conn_version']:
        save_config(r_json)
    dynamic_settings['core__remote_conn_version'] = r_json['remote_conn_version']

    for data in r_json['instances']:
        instance = Instance.objects.get(uid=data['uid'])

        if 'weather_forecast' in data:
            from simo.generic.controllers import WeatherForecast
            weather_component = Component.objects.filter(
                zone__instance=instance,
                controller_uid=WeatherForecast.uid
            ).first()
            if weather_component:
                weather_component.track_history = False
                weather_component.controller.set(data['weather_forecast'])

        instance.save()

    for user_data in r_json['users']:
        try:
            user = User.objects.get(email=user_data['email'])
        except User.DoesNotExist:
            continue
        user.name = user_data['name']
        if user_data.get('avatar_url') \
        and user.avatar_url != user_data.get('avatar_url'):
            user.avatar_url = user_data.get('avatar_url')
            resp = requests.get(user.avatar_url)
            user.avatar.save(
                os.path.basename(user.avatar_url), io.BytesIO(resp.content)
            )
            user.avatar_url = user_data.get('avatar_url')
            user.avatar_last_change = timezone.now()
        user.ssh_key = user_data.get('ssh_key')
        user.save()


@celery_app.task
def watch_timers():
    for component in Component.objects.filter(
        meta__timer_to__gt=0
    ).filter(meta__timer_to__lt=time.time()):
        component.meta['timer_to'] = 0
        component.meta['timer_start'] = 0
        component.save()
        component.controller._on_timer_end()


@celery_app.task
def clear_history():
    for instance in Instance.objects.all():
        old_times = timezone.now() - datetime.timedelta(
            days=instance.history_days
        )
        ComponentHistory.objects.filter(date__lt=old_times).delete()
        HistoryAggregate.objects.filter(start__lt=old_times).delete()


@celery_app.task
def watch_active_connections():
    # https://github.com/django/daphne/issues/319
    # Django channels and Daphne is still in active development
    # and there is something mysteriously wrong with it.
    # Sometimes daphne leaves infinite number of open sockets
    # and doesn't close them automatically
    # leading to a situation with infinite amount of daphne processes.
    # This stops only when we hit database connections limit, so new connections
    # are not being created, but hub becomes unusable to as every requrest throws
    # to many connections error.
    #
    # We use this hack to prevent uncontrollable database connections growth
    # and simply restart all processes if there are more than 50 connections.
    #
    # Usually there are no more than 20 active connections, so this ceiling
    # should be god enough.

    num_connections = 0
    with connection.cursor() as cursor:
        cursor.execute('select count(*) from pg_stat_activity;')
        num_connections = cursor.fetchone()[0]

    if num_connections > 50:
        supervisor_restart()

VACUUM_SQL = """
SELECT schemaname,relname
FROM pg_stat_all_tables
WHERE schemaname!='pg_catalog' AND schemaname!='pg_toast' AND n_dead_tup>0;
"""

@celery_app.task
def vacuum():
    from django.db import connection
    cursor = connection.cursor()
    cursor.execute(VACUUM_SQL)
    for r in cursor.fetchall():
        cursor.execute('VACUUM "%s"."%s";' % (r[0], r[1]))


@celery_app.task
def vacuum_full():
    from django.db import connection
    cursor = connection.cursor()
    cursor.execute(VACUUM_SQL)
    for r in cursor.fetchall():
        cursor.execute('VACUUM FULL "%s"."%s";' % (r[0], r[1]))


@celery_app.task
def update():
    from simo.auto_update import perform_update
    perform_update()


@celery_app.task
def update_latest_version_available():
    resp = requests.get("https://pypi.org/pypi/simo/json")
    if resp.status_code != 200:
        print("Bad response from server")
        return
    latest = list(resp.json()['releases'].keys())[-1]
    dynamic_settings['core__latest_version_available'] = latest


@celery_app.task
def drop_fingerprints_learn():
    Instance.objects.filter(
        learn_fingerprints__isnull=False,
        learn_fingerprints_start__lt=timezone.now() - datetime.timedelta(minutes=5)
    ).update(
        learn_fingerprints=None,
        learn_fingerprints_start=None
    )


@celery_app.task
def time_out_discoveries():
    from .models import Gateway
    for gw in Gateway.objects.filter(
        discovery__has_key='start'
    ).exclude(discovery__has_key='finished'):
        if time.time() - gw.discovery['start'] > gw.discovery['timeout']:
            gw.finish_discovery()


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(1, watch_timers.s())
    sender.add_periodic_task(20, sync_with_remote.s())
    sender.add_periodic_task(60 * 60, clear_history.s())
    sender.add_periodic_task(60 * 60 * 6, update_latest_version_available.s())
    sender.add_periodic_task(60, drop_fingerprints_learn.s())
