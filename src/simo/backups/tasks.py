import os, subprocess, json, uuid, datetime, shutil
from datetime import datetime, timezone
from celeryc import celery_app
from simo.conf import dynamic_settings


@celery_app.task
def check_backups():
    '''
    syncs up backups on external medium to the database
    '''
    from .models import Backup

    try:
        lv_group, lv_name, mountpoint = get_partitions()
    except:
        return Backup.objects.all().delete()


    backups_dir = os.path.join(mountpoint, 'simo_backups')
    if not os.path.exists(backups_dir):
        return Backup.objects.all().delete()

    backups_mentioned = []
    for item in os.listdir(backups_dir):
        if not item.startswith('hub-'):
            continue
        hub_mac = item.split('-')[1]
        hub_dir = os.path.join(backups_dir, item)
        for month_folder in os.listdir(hub_dir):
            try:
                year, month = month_folder.split('-')
                year, month = int(year), int(month)
            except:
                continue
            for filename in os.listdir(os.path.join(hub_dir, month_folder)):
                try:
                    day, time, back = filename.split('.')
                    hour, minute, second = time.split('-')
                    day, hour, minute, second = \
                        int(day), int(hour), int(minute), int(second)
                except:
                    continue

                obj, new = Backup.objects.update_or_create(
                    datetime=datetime(
                        year, month, day, hour, minute, second,
                        tzinfo=timezone.utc
                    ), mac=hub_mac, defaults={
                        'filepath': os.path.join(
                            hub_dir, month_folder, filename
                        )
                    }
                )
                backups_mentioned.append(obj.id)

    Backup.objects.all().exclude(id__in=backups_mentioned).delete()

    dynamic_settings['backups__last_check'] = datetime.now()


def create_snap(lv_group, lv_name):
    try:
        return subprocess.check_output(
            f'lvcreate -s -n {lv_name}-snap {lv_group}/{lv_name} -L 3G',
            shell=True
        ).decode()
    except:
        return ''


def get_lvm_partition(lsblk_data):
    for device in lsblk_data:
        if device['type'] == 'lvm' and device['mountpoint'] == '/':
            return device
        if 'children' in device:
            return get_lvm_partition(device['children'])


def get_backup_device(lsblk_data):
    for device in lsblk_data:
        if not device['hotplug']:
            continue
        target_device = None
        if device.get('fstype') == 'exfat':
            target_device = device
        elif device.get('children'):
            for child in device.get('children'):
                if child.get('fstype') == 'exfat':
                    target_device = child
        if target_device:
            return target_device


def get_partitions():

    lsblk_data = json.loads(subprocess.check_output(
        'lsblk --output NAME,HOTPLUG,MOUNTPOINT,FSTYPE,TYPE,LABEL,PARTLABEL  --json',
        shell=True
    ).decode())['blockdevices']

    # Figure out if we are running in an LVM group

    lvm_partition = get_lvm_partition(lsblk_data)
    if not lvm_partition:
        print("No LVM partition!")
        dynamic_settings['backups__last_error'] = 'No LVM partition!'
        return

    try:
        name = lvm_partition.get('name')
        split_at = name.find('-')
        lv_group = name[:split_at]
        lv_name = name[split_at + 1:].replace('--', '-')
    except:
        print("Failed to identify LVM partition")
        dynamic_settings['backups__last_error'] = \
            'Failed to identify LVM partition'
        return

    if not lv_name:
        print("LVM was not found on this system. Abort!")
        dynamic_settings['backups__last_error'] = \
            'Failed to identify LVM partition name'
        return


    # check if we have any removable devices storage devices plugged in

    backup_device = get_backup_device(lsblk_data)

    if not backup_device:
        dynamic_settings['backups__last_error'] = \
            'No external exFAT backup device on this machine'
        return

    if lvm_partition.get('partlabel'):
        mountpoint = f"/media/{backup_device['partlabel']}"
    elif lvm_partition.get('label'):
        mountpoint = f"/media/{backup_device['label']}"
    else:
        mountpoint = f"/media/{backup_device['name']}"

    if not os.path.exists(mountpoint):
        os.makedirs(mountpoint)

    if backup_device.get('mountpoint') != mountpoint:

        if backup_device.get('mountpoint'):
            subprocess.call(f"umount {backup_device['mountpoint']}", shell=True)

        subprocess.call(
            f'mount /dev/{backup_device["name"]} {mountpoint}', shell=True,
            stdout=subprocess.PIPE
        )

    return lv_group, lv_name, mountpoint


@celery_app.task
def perform_backup():

    try:
        lv_group, lv_name, mountpoint = get_partitions()
    except:
        return

    output = create_snap(lv_group, lv_name)
    if not output:
        subprocess.check_output(
            f'lvremove -f {lv_group}/{lv_name}-snap',
            shell=True
        )
        output = create_snap(lv_group, lv_name)

    if f'Logical volume "{lv_name}-snap" created' not in output:
        print(output)
        print(f"Unable to create {lv_name}-snap.")
        return

    mac = str(hex(uuid.getnode()))
    device_backups_path = f'{mountpoint}/simo_backups/hub-{mac}'
    if not os.path.exists(device_backups_path):
        os.makedirs(device_backups_path)

    now = datetime.datetime.now()
    level = now.day
    month_folder = os.path.join(
        device_backups_path, f'{now.year}-{now.month}'
    )
    if not os.path.exists(month_folder):
        os.makedirs(month_folder)
        level = 0

    if level != 0:
        # check if level 0 exists
        level_0_exists = False
        for filename in os.listdir(month_folder):
            if '-' not in filename:
                continue
            try:
                level, date = filename.split('-')
                level = int(level)
                if level == 0:
                    level_0_exists = True
                    break
            except:
                continue
        if not level_0_exists:
            print("Level 0 does not exist! Backups must be started from 0!")
            shutil.rmtree(month_folder)
            os.makedirs(month_folder)
            level = 0

    time_mark = now.strftime("%H-%M-%S")
    backup_file = f"{month_folder}/{now.day}.{time_mark}.back"
    snap_mapper = f"/dev/mapper/{lv_group}-{lv_name.replace('-', '--')}--snap"
    label = f"simo {now.strftime('%Y-%m-%d')}"
    dumpdates_file = os.path.join(month_folder, 'dumpdates')

    estimated_size = int(subprocess.check_output(
        f'dump -{level} -Squz9 -b 1024 {snap_mapper}',
        shell=True
    )) * 0.5

    folders = []
    for item in os.listdir(device_backups_path):
        if not os.path.isdir(os.path.join(device_backups_path, item)):
            continue
        try:
            year, month = item.split('-')
            folders.append([
                os.path.join(device_backups_path, item),
                int(year) * 12 + int(month)
            ])
        except:
            continue
    folders.sort(key=lambda v: v[1])

    # delete old backups to free up space required for this backup to take place
    while shutil.disk_usage('/media/backup').free < estimated_size:
        remove_folder = folders.pop()[0]
        print(f"REMOVE: {remove_folder}")
        shutil.rmtree(remove_folder)

    success = False
    try:
        subprocess.check_call(
            f'dump -{level} -quz9 -b 1024 -L "{label}" -D {dumpdates_file} -f {backup_file} {snap_mapper}',
            shell=True,
        )
        success = True
    except:
        try:
            os.remove(backup_file)
            print("Dump failed!")
        except:
            pass

    subprocess.call(
        f"lvremove -f {lv_group}/{lv_name}-snap", shell=True,
        stdout=subprocess.PIPE
    )
    if success:
        print("DONE!")
        dynamic_settings['backups__last_error'] = ''


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(60 * 60, check_backups.s())
    sender.add_periodic_task(60 * 60 * 8, perform_backup.s()) # perform auto backup every 8 hours
