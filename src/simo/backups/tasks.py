import os, subprocess, json, uuid, datetime, shutil
from datetime import datetime, timezone
from celeryc import celery_app
from simo.conf import dynamic_settings
from simo.core.utils.helpers import get_random_string


@celery_app.task
def check_backups():
    '''
    syncs up backups on external medium to the database
    '''
    from simo.backups.models import Backup, BackupLog

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
                    day, time, level, back = filename.split('.')
                    hour, minute, second = time.split('-')
                    day, hour, minute, second, level = \
                        int(day), int(hour), int(minute), int(second), int(level)
                except:
                    continue

                filepath = os.path.join(hub_dir, month_folder, filename)
                file_stats = os.stat(filepath)
                obj, new = Backup.objects.update_or_create(
                    datetime=datetime(
                        year, month, day, hour, minute, second,
                        tzinfo=timezone.utc
                    ), mac=hub_mac, defaults={
                        'filepath': filepath, 'level': level,
                        'size': file_stats.st_size
                    }
                )
                backups_mentioned.append(obj.id)

    Backup.objects.all().exclude(id__in=backups_mentioned).delete()

    dynamic_settings['backups__last_check'] = int(datetime.now().timestamp())


def create_snap(lv_group, lv_name):
    try:
        return subprocess.check_output(
            f'lvcreate -s -n {lv_name}-snap {lv_group}/{lv_name} -L 5G',
            shell=True
        ).decode()
    except:
        return


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
    from simo.backups.models import BackupLog

    lsblk_data = json.loads(subprocess.check_output(
        'lsblk --output NAME,HOTPLUG,MOUNTPOINT,FSTYPE,TYPE,LABEL,PARTLABEL  --json',
        shell=True
    ).decode())['blockdevices']

    # Figure out if we are running in an LVM group

    lvm_partition = get_lvm_partition(lsblk_data)
    if not lvm_partition:
        print("No LVM partition!")
        BackupLog.objects.create(
            level='warning', msg="Can't backup. No LVM partition!"
        )
        return

    try:
        name = lvm_partition.get('name')
        split_at = name.find('-')
        lv_group = name[:split_at]
        lv_name = name[split_at + 1:].replace('--', '-')
    except:
        print("Failed to identify LVM partition")
        BackupLog.objects.create(
            level='warning', msg="Can't backup. Failed to identify LVM partition."
        )
        return

    if not lv_name:
        print("LVM was not found on this system. Abort!")
        BackupLog.objects.create(
            level='warning',
            msg="Can't backup. Failed to identify LVM partition name."
        )
        return


    # check if we have any removable devices storage devices plugged in

    backup_device = get_backup_device(lsblk_data)

    if not backup_device:
        BackupLog.objects.create(
            level='warning',
            msg="Can't backup. No external exFAT backup device on this machine."
        )
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
    from simo.backups.models import BackupLog
    try:
        lv_group, lv_name, mountpoint = get_partitions()
    except:
        return

    output = create_snap(lv_group, lv_name)
    if not output or f'Logical volume "{lv_name}-snap" created' not in output:
        try:
            subprocess.check_output(
                f'lvremove -f {lv_group}/{lv_name}-snap',
                shell=True
            )
        except:
            pass
        output = create_snap(lv_group, lv_name)

    if f'Logical volume "{lv_name}-snap" created' not in output:
        print(output)
        print(f"Unable to create {lv_name}-snap.")
        return

    mac = str(hex(uuid.getnode()))
    device_backups_path = f'{mountpoint}/simo_backups/hub-{mac}'
    if not os.path.exists(device_backups_path):
        os.makedirs(device_backups_path)

    now = datetime.now()
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
    backup_file = f"{month_folder}/{now.day}.{time_mark}.{level}.back"
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
            BackupLog.objects.create(
                level='error', msg="Can't backup. Dump failed."
            )
            print("Dump failed!")
        except:
            pass

    subprocess.call(
        f"lvremove -f {lv_group}/{lv_name}-snap", shell=True,
        stdout=subprocess.PIPE
    )
    if success:
        print("DONE!")
        BackupLog.objects.create(
            level='info', msg="Backup success!"
        )


@celery_app.task
def restore_backup(backup_id):
    from simo.backups.models import Backup, BackupLog
    backup = Backup.objects.get(id=backup_id)

    try:
        lv_group, lv_name, mpt = get_partitions()
    except:
        BackupLog.objects.create(
            level='error',
            msg="Can't restore. LVM group is not present on this machine."
        )
        return

    snap_name = f'{lv_name}-{get_random_string(5)}'
    output = create_snap(lv_group, snap_name)
    if not output or f'Logical volume "{lv_name}-snap" created' not in output:
        BackupLog.objects.create(
            level='error',
            msg="Can't restore. Can't create LVM snapshot\n\n" + output
        )
        return

    if not os.path.exists('/var/backups/simo-main'):
        os.makedirs('/var/backups/simo-main')

    subprocess.call('umount /var/backup/simo-main', shell=True)

    subprocess.call('rm -rf /var/backup/simo-main/*', shell=True)

    subprocess.call(
        f"mount /dev/mapper/{lv_group}-{snap_name.replace('-', '--')} /var/backup/simo-main",
        shell=True, stdout=subprocess.PIPE
    )
    try:
        subprocess.call(
            f"restore -C -v -b 1024 -f {backup.filepath} -D /var/backup/simo-main",
            shell=True
        )
        subprocess.call(
            f"lvconvert --mergesnapshot {lv_group}/{snap_name}",
            shell=True
        )
    except Exception as e:
        BackupLog.objects.create(
            level='error',
            msg="Can't restore. \n\n" + str(e)
        )
        subprocess.call('umount /var/backup/simo-main', shell=True)
        subprocess.call(
            f"lvremove -f {lv_group}/{snap_name}", shell=True,
            stdout=subprocess.PIPE
        )
    else:
        print("All good! REBOOT!")
        subprocess.call('reboot')


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(60 * 60, check_backups.s())
    sender.add_periodic_task(60 * 60 * 8, perform_backup.s()) # perform auto backup every 8 hours
