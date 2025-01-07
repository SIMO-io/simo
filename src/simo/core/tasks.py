import time
import os
import io
import json
import datetime
import requests
import subprocess
import threading
import pkg_resources
import uuid
from django.db.models import Q
from django.db import connection, transaction
from django.template.loader import render_to_string
from celeryc import celery_app
from django.utils import timezone
from actstream.models import Action
from simo.conf import dynamic_settings
from simo.core.utils.helpers import get_self_ip
from simo.core.middleware import introduce_instance
from simo.users.models import PermissionsRole, InstanceUser
from .models import Instance, Component, ComponentHistory, HistoryAggregate


@celery_app.task
def supervisor_restart():
    time.sleep(2)
    subprocess.run(['redis-cli', 'flushall'])
    subprocess.run(['supervisorctl', 'restart', 'all'])


@celery_app.task
def hardware_reboot():
    time.sleep(2)
    print("Reboot system")
    subprocess.run(['reboot'])


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
        try:
            subprocess.run(
                ['service', 'openvpn', 'reload']
            )
        except:
            pass

    if vpn_change:
        threading.Thread(target=restart_openvpn).start()


@celery_app.task
def sync_with_remote():
    from simo.users.models import User

    try:
        mac = str(hex(uuid.getnode()))
    except:
        mac = ''

    try:
        version = pkg_resources.get_distribution('simo').version
    except:
        version = 'dev'

    report_data = {
        'simo_version': version,
        'local_http': 'https://%s' % get_self_ip(),
        'mac': mac,
        'hub_uid': dynamic_settings['core__hub_uid'],
        'hub_secret': dynamic_settings['core__hub_secret'],
        'remote_conn_version': dynamic_settings['core__remote_conn_version'],
        'instances': []
    }
    for instance in Instance.objects.filter(is_active=True):
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

        users_included = set()
        for iuser in instance.instance_users.all().select_related('user', 'role'):
            instance_data['users'].append({
                'email': iuser.user.email,
                'is_hub_master': iuser.user.is_master,
                'is_superuser': iuser.role.is_superuser,
                'is_owner': iuser.role.is_owner,
                'is_active': iuser.is_active,
                'device_token': iuser.user.primary_device_token
            })
            users_included.add(iuser.user.id)

        # Include god mode users!
        for user in User.objects.filter(
            is_master=True
        ).exclude(
            email__in=('system@simo.io', 'device@simo.io')
        ).exclude(id__in=users_included).distinct():
            if not user.is_active:
                continue
            instance_data['users'].append({
                'email': user.email,
                'is_hub_master': True,
                'is_superuser': False,
                'is_owner': False,
                'is_active': True,
                'device_token': user.primary_device_token
            })

        last_event = ComponentHistory.objects.filter(
            component__zone__instance=instance
        ).order_by('-date').first()
        if last_event:
            instance_data['last_event'] = last_event.date.timestamp()

        report_data['instances'].append(instance_data)

    print("Sync UP with remote: ", json.dumps(report_data))

    response = requests.post('https://simo.io/hubs/sync/', json=report_data)
    if response.status_code != 200:
        print("Faled! Response code: ", response.status_code)
        return

    r_json = response.json()

    print("Responded with: ", json.dumps(r_json))


    if 'hub_uid' in r_json:
        dynamic_settings['core__hub_uid'] = r_json['hub_uid']

    dynamic_settings['core__remote_http'] = r_json.get('hub_remote_http', '')
    if 'new_secret' in r_json:
        dynamic_settings['core__hub_secret'] = r_json['new_secret']

    if dynamic_settings['core__remote_conn_version'] < r_json['remote_conn_version']:
        save_config(r_json)
    dynamic_settings['core__remote_conn_version'] = r_json['remote_conn_version']

    instance_uids = []
    for data in r_json['instances']:
        users_data = data.pop('users', {})
        instance_uid = data.pop('uid')
        instance_uids.append(instance_uid)
        weather = data.pop('weather', None)
        instance, new_instance = Instance.objects.update_or_create(
            uid=instance_uid, defaults=data
        )
        if not instance.is_active:
            instance.is_active = True
            instance.save()

        if weather:
            from simo.generic.controllers import Weather
            weather_component = Component.objects.filter(
                zone__instance=instance,
                controller_uid=Weather.uid
            ).first()
            if weather_component:
                weather_component.track_history = False
                weather_component.controller.set(weather)
                weather_component.save()

        if new_instance:
            print(f"NEW INSTANCE: {instance}")
            print(f"Users data: {users_data}")


        for email, options in users_data.items():
            if new_instance:
                print(f"EMAIL: {email}")
                print(f"OPTIONS: {options}")
            if new_instance or not instance.instance_users.count():
                # Create user for new instance!
                user, new_user = User.objects.get_or_create(
                    email=email, defaults={
                    'name': options.get('name'),
                    'is_master': options.get('is_hub_master', False),
                })
                role = None
                if options.get('is_superuser'):
                    print(f"Try getting superuser role!")
                    role = PermissionsRole.objects.filter(
                        instance=instance, is_superuser=True
                    ).first()
                    if role:
                        print("ROLE FOUND: ", role)
                    else:
                        print("NO such a role.")
                elif options.get('is_owner'):
                    print(f"Try getting owner role!")
                    role = PermissionsRole.objects.filter(
                        instance=instance, is_owner=True, is_superuser=False
                    ).first()
                    if role:
                        print("ROLE FOUND: ", role)
                    else:
                        print("NO such a role.")

                if role:
                    print("Creating InstanceUser!")
                    InstanceUser.objects.update_or_create(
                        user=user, instance=instance, defaults={
                            'is_active': True, 'role': role
                        }
                    )
                else:
                    print("Instance User was not created!")
            else:
                user = User.objects.filter(email=email).first()

            if not user:
                continue

            if user.name != options.get('name'):
                user.name = options['name']
                user.save()

            avatar_url = options.get('avatar_url')
            if avatar_url and user.avatar_url != avatar_url:
                resp = requests.get(avatar_url)
                user.avatar.save(
                    os.path.basename(avatar_url), io.BytesIO(resp.content)
                )
                user.avatar_url = avatar_url
                user.avatar_last_change = timezone.now()
                user.save()



@celery_app.task
def clear_history():
    for instance in Instance.objects.all():
        print(f"Clear history of {instance}")
        introduce_instance(instance)
        old_times = timezone.now() - datetime.timedelta(
            days=instance.history_days
        )
        ComponentHistory.objects.filter(
            component__zone__instance=instance, date__lt=old_times
        ).delete()
        i = 0
        delete_ids = []
        for obj in ComponentHistory.objects.filter(
            component__zone__instance=instance
        ).order_by('-date').values('id').iterator():
            if i < 5000:
                continue
            delete_ids.append(obj['id'])
        ComponentHistory.objects.filter(id__in=delete_ids)
        HistoryAggregate.objects.filter(
            component__zone__instance=instance, start__lt=old_times
        ).delete()
        i = 0
        delete_ids = []
        for obj in HistoryAggregate.objects.filter(
            component__zone__instance=instance
        ).order_by('-start').values('id').iterator():
            if i < 1000:
                continue
            delete_ids.append(obj['id'])
        HistoryAggregate.objects.filter(id__in=delete_ids)
        Action.objects.filter(
            data__instance_id=instance.id, timestamp__lt=old_times
        )
        i = 0
        delete_ids = []
        for obj in Action.objects.filter(
            data__instance_id=instance.id
        ).order_by('-timestamp').values('id').iterator():
            if i < 5000:
                continue
            delete_ids.append(obj['id'])
        Action.objects.filter(id__in=delete_ids)


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
    from simo.core.management.update import perform_update
    perform_update()


@celery_app.task
def drop_fingerprints_learn():
    Instance.objects.filter(
        is_active=True,
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


@celery_app.task
def restart_postgresql():
    # restart postgresql daily, so that we do not get in to any kind of
    # hanging connections left by Django, which might happen if things are
    # running for months without a reboot.
    proc = subprocess.Popen(
        ['service', 'postgresql', 'restart']
    )
    proc.communicate()


@celery_app.task
def low_battery_notifications():
    from simo.notifications.utils import notify_users
    from simo.automation.helpers import be_or_not_to_be
    for instance in Instance.objects.filter(is_active=True):
        timezone.activate(instance.timezone)
        hour = timezone.localtime().hour
        if hour < 7:
            continue
        if hour > 21:
            continue

        introduce_instance(instance)
        for comp in Component.objects.filter(
            zone__instance=instance,
            battery_level__isnull=False, battery_level__lt=20
        ):
            last_warning = comp.meta.get('last_battery_warning', 0)
            notify = be_or_not_to_be(12 * 60 * 60, 72 * 60 * 60, last_warning)
            if not notify:
                continue

            iusers = comp.zone.instance.instance_users.filter(
                is_active=True, role__is_owner=True
            )
            if iusers:
                notify_users(
                    'warning',
                    f"Low battery ({comp.battery_level}%) on {comp}",
                    component=comp, instance_users=iusers
                )
            comp.meta['last_battery_warning'] = time.time()
            comp.save()


@celery_app.task
def maybe_update_to_latest():
    from simo.core.models import Instance
    from simo.conf import dynamic_settings
    resp = requests.get("https://pypi.org/pypi/simo/json")
    if resp.status_code != 200:
        print("Bad response from server")
        return

    versions = list(resp.json()['releases'].keys())
    def version_no(v):
        major, minor, patch = v.split('.')
        return int(major) * 1000000 + int(minor) * 1000 + int(patch)
    versions.sort(reverse=True, key=version_no)
    dynamic_settings['core__latest_version_available'] = versions[0]

    try:
        version = pkg_resources.get_distribution('simo').version
    except:
        # dev environment
        version = dynamic_settings['core__latest_version_available']

    if dynamic_settings['core__latest_version_available'] == version:
        print("Up to date!")
        return

    if not Instance.objects.all().count() or dynamic_settings['core__auto_update']:
        print("Need to update!!")
        return update.s()

    print("New version is available, but auto update is disabled.")


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(20, sync_with_remote.s())
    sender.add_periodic_task(60 * 60, clear_history.s())
    sender.add_periodic_task(60 * 60, maybe_update_to_latest.s())
    sender.add_periodic_task(60, drop_fingerprints_learn.s())
    sender.add_periodic_task(60 * 60 * 24, restart_postgresql.s())
    sender.add_periodic_task(60 * 60, low_battery_notifications.s())
