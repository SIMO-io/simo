import os, subprocess, json, uuid, datetime, shutil, pytz
from datetime import datetime, timedelta
from django.utils import timezone
from celeryc import celery_app
from simo.conf import dynamic_settings
from simo.core.utils.helpers import get_random_string


@celery_app.task
def check_backups():
    '''
    syncs up backups on external medium to the database
    '''
    from simo.backups.models import Backup

    try:
        lv_group, lv_name, sd_mountpoint = get_partitions()
    except:
        return Backup.objects.all().delete()


    backups_dir = os.path.join(sd_mountpoint, 'simo_backups')
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

            month_folder_path = os.path.join(hub_dir, month_folder)
            res = subprocess.run(
                f"borg list {month_folder_path} --json",
                shell=True, stdout=subprocess.PIPE
            )
            try:
                archives = json.loads(res.stdout.decode())['archives']
            except Exception as e:
                continue

            for archive in archives:
                make_datetime = datetime.fromisoformat(archive['start'])
                make_datetime = make_datetime.replace(tzinfo=pytz.UTC)
                filepath = f"{month_folder_path}::{archive['name']}"

                obj, new = Backup.objects.update_or_create(
                    datetime=make_datetime, mac=hub_mac, defaults={
                        'filepath': f"{month_folder_path}::{archive['name']}",
                    }
                )
                backups_mentioned.append(obj.id)

    Backup.objects.all().exclude(id__in=backups_mentioned).delete()

    dynamic_settings['backups__last_check'] = int(datetime.now().timestamp())


def clean_backup_snaps(lv_group, lv_name):
    res = subprocess.run(
        'lvs --report-format json', shell=True, stdout=subprocess.PIPE
    )
    lvs_data = json.loads(res.stdout.decode())
    for volume in lvs_data['report'][0]['lv']:
        if volume['vg_name'] != lv_group:
            continue
        if volume['origin'] != lv_name:
            continue
        if not volume['lv_name'].startswith(f"{lv_name}-bk-"):
            continue
        subprocess.run(
            f"lvremove -f {lv_group}/{volume['lv_name']}", shell=True
        )



def create_snap(lv_group, lv_name, snap_name=None, size=None, try_no=1):
    '''
    :param lv_group:
    :param lv_name:
    :param snap_name: random snap name will be generated if not provided
    :param size: Size in GB. If not provided, maximum available space in lvm will be used.
    :return: snap_name
    '''
    if not snap_name:
        snap_name = f"{lv_name}-bk-{get_random_string(5)}"

    clean_backup_snaps(lv_group, lv_name)

    res = subprocess.run(
        'vgs --report-format json', shell=True, stdout=subprocess.PIPE
    )
    try:
        vgs_data = json.loads(res.stdout.decode())
        free_space = vgs_data['report'][0]['vg'][0]['vg_free']
    except:
        if try_no < 3:
            clean_backup_snaps(lv_group, lv_name)
            return create_snap(lv_group, lv_name, snap_name, size, try_no+1)
        raise Exception("Unable to find free space on LVM!")

    if not free_space.lower().endswith('g'):
        if try_no < 3:
            clean_backup_snaps(lv_group, lv_name)
            return create_snap(lv_group, lv_name, snap_name, size, try_no+1)
        raise Exception("Not enough free space on LVM!")

    free_space = int(float(
        vgs_data['report'][0]['vg'][0]['vg_free'].strip('g').strip('<')
    ))

    if not size:
        size = free_space
    else:
        if size > free_space:
            if try_no < 3:
                clean_backup_snaps(lv_group, lv_name)
                return create_snap(lv_group, lv_name, snap_name, size, try_no + 1)
            raise Exception(
                f"There's only {free_space}G available on LVM, "
                f"but you asked for {size}G"
            )

    res = subprocess.run(
        f'lvcreate -s -n {snap_name} {lv_group}/{lv_name} -L {size}G',
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if res.returncode:
        raise Exception(res.stderr)

    return snap_name



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
        sd_mountpoint = f"/media/{backup_device['partlabel']}"
    elif lvm_partition.get('label'):
        sd_mountpoint = f"/media/{backup_device['label']}"
    else:
        sd_mountpoint = f"/media/{backup_device['name']}"

    if not os.path.exists(sd_mountpoint):
        os.makedirs(sd_mountpoint)

    if backup_device.get('mountpoint') != sd_mountpoint:

        if backup_device.get('mountpoint'):
            subprocess.call(f"umount {backup_device['mountpoint']}", shell=True)

        subprocess.call(
            f'mount /dev/{backup_device["name"]} {sd_mountpoint}', shell=True,
            stdout=subprocess.PIPE
        )

    return lv_group, lv_name, sd_mountpoint


@celery_app.task
def perform_backup():
    from simo.backups.models import BackupLog
    try:
        lv_group, lv_name, sd_mountpoint = get_partitions()
    except:
        return

    snap_mount_point = '/var/backups/simo-main'
    subprocess.run(f'umount {snap_mount_point}', shell=True)

    try:
        snap_name = create_snap(lv_group, lv_name)
    except Exception as e:
        print("Error creating temporary snap\n" + str(e))
        BackupLog.objects.create(
            level='error',
            msg="Backup error. Unable to create temporary snap\n" + str(e)
        )
        return

    shutil.rmtree(snap_mount_point, ignore_errors=True)
    os.makedirs(snap_mount_point)
    subprocess.run([
        "mount",
         f"/dev/mapper/{lv_group}-{snap_name.replace('-', '--')}",
         snap_mount_point
    ])

    mac = str(hex(uuid.getnode()))
    device_backups_path = f'{sd_mountpoint}/simo_backups/hub-{mac}'


    now = datetime.now()
    month_folder = os.path.join(
        device_backups_path, f'{now.year}-{now.month}'
    )
    if not os.path.exists(month_folder):
        os.makedirs(month_folder)
        subprocess.run(
            f'borg init --encryption=none {month_folder}', shell=True
        )
    else:
        res = subprocess.run(
            f'borg info --json {month_folder}',
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if res.returncode:
            shutil.rmtree(month_folder)
            subprocess.run(
                f'borg init --encryption=none {month_folder}', shell=True
            )

    exclude_dirs = (
        'tmp', 'lost+found', 'proc', 'cdrom', 'dev', 'mnt', 'sys', 'run',
        'var/tmp', 'var/cache', 'var/log', 'media',
    )
    backup_command = 'borg create --compression lz4'
    for dir in exclude_dirs:
        backup_command += f' --exclude={dir}'


    other_month_folders = []
    for item in os.listdir(device_backups_path):
        if not os.path.isdir(os.path.join(device_backups_path, item)):
            continue
        if os.path.join(device_backups_path, item) == month_folder:
            continue
        try:
            year, month = item.split('-')
            other_month_folders.append([
                os.path.join(device_backups_path, item),
                int(year) * 12 + int(month)
            ])
        except:
            continue
    other_month_folders.sort(key=lambda v: v[1])

    if other_month_folders:
        # delete old backups to free up at least 20G of space
        while shutil.disk_usage('/media/backup').free < 20 * 1024 * 1024 * 1024:
            remove_folder = other_month_folders.pop()[0]
            print(f"REMOVE: {remove_folder}")
            shutil.rmtree(remove_folder)

    backup_command += f' {month_folder}::{get_random_string()} .'
    res = subprocess.run(
        backup_command, shell=True, cwd=snap_mount_point,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    subprocess.run(["umount", snap_mount_point])
    subprocess.run(
        f"lvremove -f {lv_group}/{snap_name}", shell=True
    )

    if res.returncode:
        print("Backup error!")
        BackupLog.objects.create(
            level='error', msg="Backup error: \n" + res.stderr.decode()
        )
    else:
        print("Backup done!")
        BackupLog.objects.create(
            level='info', msg="Backup success!"
        )


@celery_app.task
def restore_backup(backup_id):
    from simo.backups.models import Backup, BackupLog
    backup = Backup.objects.get(id=backup_id)

    try:
        lv_group, lv_name, sd_mountpoint = get_partitions()
    except:
        BackupLog.objects.create(
            level='error',
            msg="Can't restore. LVM group is not present on this machine."
        )
        return

    snap_mount_point = '/var/backups/simo-main'
    subprocess.run(f'umount {snap_mount_point}', shell=True)

    try:
        snap_name = create_snap(lv_group, lv_name)
    except Exception as e:
        print("Error creating temporary snap\n" + str(e))
        BackupLog.objects.create(
            level='error',
            msg="Can't restore. \n\n" + str(e)
        )
        return

    shutil.rmtree(snap_mount_point, ignore_errors=True)
    os.makedirs(snap_mount_point)
    subprocess.run([
        "mount",
        f"/dev/mapper/{lv_group}-{snap_name.replace('-', '--')}",
        snap_mount_point
    ])

    # delete current contents of a snap
    print("Delete original files and folders")
    for f in os.listdir(snap_mount_point):
        shutil.rmtree(os.path.join(snap_mount_point, f), ignore_errors=True)

    print("Perform restoration")
    res = subprocess.run(
        f"borg extract {backup.filepath}", shell=True, cwd=snap_mount_point,
        stderr=subprocess.PIPE
    )

    subprocess.run(["umount", snap_mount_point])
    subprocess.run(
        f"lvremove -f {lv_group}/{snap_name}", shell=True
    )

    if res.returncode:
        BackupLog.objects.create(
            level='error',
            msg="Can't restore. \n\n" + res.stderr.decode()
        )
    else:
        print("Restore successful! Merge snapshot and reboot!")
        subprocess.call(
            f"lvconvert --mergesnapshot {lv_group}/{snap_name}",
            shell=True
        )
        subprocess.run('reboot', shell=True)


@celery_app.task
def clean_old_logs():
    from .models import BackupLog
    BackupLog.objects.filter(
        datetime__lt=timezone.now() - timedelta(days=90)
    )


@celery_app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(60 * 60, check_backups.s())
    # perform auto backup every 12 hours
    sender.add_periodic_task(60 * 60 * 12, perform_backup.s())
    sender.add_periodic_task(60 * 60, clean_old_logs.s())
