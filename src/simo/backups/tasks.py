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
    """Return the *lsblk* entry describing the logical volume mounted as "/".

    The original implementation returned prematurely when the first top-level
    device contained any children – even if none of them matched the search
    criteria.  As a result the search stopped after inspecting just a single
    branch of the device tree which broke setups where the root logical
    volume was not located under the very first block device listed by
    *lsblk* (e.g. when the machine had multiple drives).

    The fixed version walks the whole tree depth-first and stops only after a
    matching entry is found or the entire structure has been inspected.
    """

    for device in lsblk_data:
        # Check the current node first.
        if device.get('type') == 'lvm' and device.get('mountpoint') == '/':
            return device

        # Recursively search children (if any).  The recursive call returns
        # either the desired dictionary or *None* – propagate the first truthy
        # value up the call stack so that the outermost caller gets the
        # matching entry.
        child_match = get_lvm_partition(device.get('children', [])) if device.get('children') else None
        if child_match:
            return child_match

    # Nothing found on this branch.
    return None


def _has_backup_label(dev: dict) -> bool:
    """Return ``True`` when the given *lsblk* device description represents
    the desired "backup" partition.  The logic is kept in one place to make
    future adjustments simpler.

    The criteria as of now are:

    The filesystem label (``label`` field) is exactly ``BACKUP`` – this is
    how the pre-built *rescue.img* image names the 3rd partition that
    will be used for storing backups.
    """

    label = (dev.get("label") or dev.get("partlabel") or "").upper()
    if label == "BACKUP":
        return True
    return False


def get_backup_device(lsblk_data):
    """Locate a removable partition that should be used to store backups.

    Priority is given to a partition explicitly labelled ``BACKUP``.  If such
    a partition isn't found, the legacy rule – ‘any removable exFAT
    partition’ – is used.
    """

    _MIN_SIZE_BYTES = 32 * 1024 * 1024 * 1024  # 32 GiB – keep in sync with
                                               # _find_blank_removable_device.

    def _device_size_bytes(dev_name: str):
        """Return size of *dev_name* in bytes (or ``None`` on failure)."""

        for cmd in (
            f"blockdev --getsize64 /dev/{dev_name}",
            f"lsblk -b -dn -o SIZE /dev/{dev_name}",
        ):
            try:
                out = subprocess.check_output(
                    cmd, shell=True, stderr=subprocess.DEVNULL
                ).strip()
                return int(out)
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Helper: does the filesystem already contain legacy backups?
    # ------------------------------------------------------------------

    def _entry_has_simo_backups(entry: dict) -> bool:
        """Return *True* when *entry* hosts legacy ``simo_backups`` folder.

        The implementation borrows heavily from the _fs_is_empty() helper –
        we temporarily mount the filesystem read-only when it is not mounted
        yet, inspect the directory listing and clean everything up.
        """

        mountpoint = entry.get("mountpoint")
        cleanup = False

        if not mountpoint:
            tmp_dir = f"/tmp/simo-bk-{uuid.uuid4().hex[:8]}"
            try:
                os.makedirs(tmp_dir, exist_ok=True)
                res = subprocess.run(
                    f"mount -o ro /dev/{entry['name']} {tmp_dir}",
                    shell=True,
                    stderr=subprocess.PIPE,
                )
                if res.returncode:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    return False
                mountpoint = tmp_dir
                cleanup = True
            except Exception:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return False

        has_backups = os.path.isdir(os.path.join(mountpoint, "simo_backups"))

        if cleanup:
            subprocess.run(f"umount {mountpoint}", shell=True)
            shutil.rmtree(mountpoint, ignore_errors=True)

        return has_backups

    # ------------------------------------------------------------------
    # Phase 1 – look for properly prepared BACKUP partition **>=32 GiB**.
    #          This is the preferred modern approach.
    # ------------------------------------------------------------------

    for device in lsblk_data:
        if not device.get("hotplug"):
            continue

        # Capacity check – skip devices smaller than the required threshold.
        size_bytes = _device_size_bytes(device["name"])
        if size_bytes is None:
            print(f"Could not obtain capacity of: {device['name']}")
            continue

        if size_bytes < _MIN_SIZE_BYTES:
            continue

        # Prefer partitions explicitly labelled "BACKUP".
        for child in device.get("children", []):
            if _has_backup_label(child):
                return child

    # ------------------------------------------------------------------
    # Phase 2 – look for **existing** legacy backup drives.
    # ------------------------------------------------------------------

    if _find_blank_removable_device(lsblk_data):
        # New empty disk is available, let's use it instead of trying to find
        # legacy media
        return None

    for device in lsblk_data:
        if not device.get("hotplug"):
            continue

        # Check the whole device first.
        if device.get("mountpoint") or device.get("fstype"):
            if _entry_has_simo_backups(device):
                return device

        # Check its partitions (if any).
        for child in device.get("children", []):
            if _entry_has_simo_backups(child):
                return child

    # Nothing has been found.
    return None


def _find_blank_removable_device(lsblk_data):
    """Return the first removable block *device* that looks empty.

    A device is considered *blank* when one of the following conditions is
    met:

    1. It has no children (partitions) **and** no recognised filesystem – the
       original behaviour that covers brand-new, uninitialised drives.
    2. It has no children (partitions) **and** an existing filesystem that is
       effectively empty (e.g. a freshly formatted card).

    Determining if a filesystem is *empty* is tricky without mounting it, but
    for the purpose of automatically provisioning backup media we can use a
    pragmatic heuristic: if the device is not mounted we temporarily mount it
    read-only to a throw-away directory, inspect its contents and then unmount
    it again.  If it **is** already mounted we reuse the existing
    mount-point.  In both cases we treat the device as blank when the root of
    the filesystem contains no entries other than implementation-specific
    placeholders like the *lost+found* directory created by *mkfs.ext4*.

    This relaxed definition allows the backup subsystem to reuse drives that
    have been pre-formatted by the user but never actually used to store any
    files.
    """

# --- Helper inner functions ------------------------------------------------

    def _device_size_bytes(dev_name: str):
        """Return size of *dev_name* in bytes (or ``None`` on failure)."""

        for cmd in (
            f"blockdev --getsize64 /dev/{dev_name}",
            f"lsblk -b -dn -o SIZE /dev/{dev_name}",
        ):
            try:
                out = subprocess.check_output(
                    cmd, shell=True, stderr=subprocess.DEVNULL
                ).strip()
                return int(out)
            except Exception:
                continue
        return None

    def _fs_is_empty(entry: dict) -> bool:
        """Heuristic to decide if a filesystem represented by *entry* is empty."""

        fstype = entry.get("fstype")
        if not fstype:
            # Unformatted – treat as empty.
            return True

        mountpoint = entry.get("mountpoint")
        cleanup = False

        if not mountpoint:
            tmp_dir = f"/tmp/simo-bk-{uuid.uuid4().hex[:8]}"
            try:
                os.makedirs(tmp_dir, exist_ok=True)
                res = subprocess.run(
                    f"mount -o ro /dev/{entry['name']} {tmp_dir}",
                    shell=True,
                    stderr=subprocess.PIPE,
                )
                if res.returncode:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    print(f"Unable to mount {entry['name']} to inspect contents – skip")
                    return False
                mountpoint = tmp_dir
                cleanup = True
            except Exception as exc:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                print(f"Exception while mounting {entry['name']}: {exc}")
                return False

        try:
            with os.scandir(mountpoint) as it:
                entries = [e.name for e in it if not e.name.startswith('.')]
        except Exception as exc:
            print(f"Unable to read directory listing for {entry['name']}: {exc}")
            if cleanup:
                subprocess.run(f"umount {mountpoint}", shell=True)
                shutil.rmtree(mountpoint, ignore_errors=True)
            return False

        if cleanup:
            subprocess.run(f"umount {mountpoint}", shell=True)
            shutil.rmtree(mountpoint, ignore_errors=True)

        meaningful = [e for e in entries if e not in {"lost+found"}]
        return not meaningful

# ---------------------------------------------------------------------------

    _MIN_SIZE_BYTES = 32 * 1024 * 1024 * 1024  # 32 GiB

    for device in lsblk_data:
        if not device.get("hotplug"):
            continue

        size_bytes = _device_size_bytes(device["name"])
        if size_bytes is None:
            print(f"Could not obtain capacity of: {device['name']}")
            continue

        if size_bytes < _MIN_SIZE_BYTES:
            print(f"Too small (<32 GiB): {device['name']}")
            continue

        children = device.get("children") or []

        if not children:
            # Whole-disk filesystem.
            if _fs_is_empty(device):
                return device
            print(f"Whole-disk filesystem on {device['name']} is not empty – skip")
            continue

        if len(children) == 1:
            child = children[0]
            if _fs_is_empty(child):
                return device
            print(f"Single partition {child['name']} on {device['name']} is not empty – skip")
            continue

        print(f"More than one partition on {device['name']} – skip")

    return None


def _ensure_rescue_image_written(blank_device_name: str):
    """Write *rescue.img* to the given **whole-disk** device.

    The function is intentionally idempotent – if writing fails the caller can
    attempt to call it again (e.g. the next time the periodic task runs).

    It raises an exception on irrecoverable errors so that the caller can log
    the failure.
    """

    import tarfile, time

    img_path = os.path.join(os.path.dirname(__file__), "rescue.img.xz")

    # Write the image.  We deliberately avoid using *python-dd* wrappers and
    # rely on the time-tested `dd(1)` command.
    dd_cmd = (
        f"xzcat {img_path} | dd of=/dev/{blank_device_name} bs=4M conv=fsync"
    )
    res = subprocess.run(dd_cmd, shell=True, stderr=subprocess.PIPE)
    if res.returncode:
        raise RuntimeError(
            f"Writing rescue image failed: {res.stderr.decode(errors='ignore')}"
        )

    # Make sure the kernel notices the new partition table.
    subprocess.run(f"partprobe /dev/{blank_device_name}", shell=True)

    # Give the device a moment to settle.
    time.sleep(2)

    # Enlarge the 3rd partition (BACKUP) to the rest of the disk and create /
    # extend the exFAT filesystem.  This is wrapped in a helper to keep the
    # main flow readable.
    _expand_backup_partition(blank_device_name)


def _expand_backup_partition(device_name: str):
    """Make partition 3 span leftover space and be ext4 labelled BACKUP.

    Implementation is intentionally minimal and resilient:
    – Use *sgdisk* only (no interactive prompts).
    – Delete partition 3 (if present) and create a new one that fills all
      remaining free space.
    – Always create a fresh ext4 filesystem labelled BACKUP.
    Because the rescue-image just flashed is empty, data loss is not a
    concern and this deterministic route avoids edge-case errors.
    """

    import time, shutil

    def _dev_path(base: str) -> str:
        """Return /dev/<base>3 path handling devices that need 'p3'."""
        direct = f"/dev/{base}3"
        with_p = f"/dev/{base}p3"
        return direct if os.path.exists(direct) else with_p

    # 1. Ensure GPT headers cover the whole disk (harmless if already OK).
    subprocess.run(f"sgdisk -e /dev/{device_name}", shell=True)

    # 2. Drop existing partition 3 (ignore errors when it does not exist).
    subprocess.run(f"sgdisk -d 3 /dev/{device_name}", shell=True)

    # 3. Create new Linux filesystem partition occupying the rest of the disk.
    create_cmd = f"sgdisk -n 3:0:0 -t 3:8300 -c 3:BACKUP /dev/{device_name}"
    res = subprocess.run(create_cmd, shell=True, stderr=subprocess.PIPE)
    if res.returncode:
        raise RuntimeError(
            "sgdisk failed to create BACKUP partition: " +
            res.stderr.decode(errors="ignore")
        )

    # 4. Inform kernel and wait for udev.
    subprocess.run(f"partprobe /dev/{device_name}", shell=True)
    subprocess.run("udevadm settle", shell=True)

    part_path = _dev_path(device_name)
    for _ in range(5):
        if os.path.exists(part_path):
            break
        time.sleep(1)
    else:
        raise RuntimeError("/dev node for new BACKUP partition did not appear")

    # 5. Always create a fresh ext4 filesystem; wipe old signatures first.
    subprocess.run(f"wipefs -a {part_path}", shell=True)
    mkfs_cmd = f"mkfs.ext4 -F -L BACKUP {part_path}"
    res = subprocess.run(mkfs_cmd, shell=True, stderr=subprocess.PIPE)
    if res.returncode:
        raise RuntimeError(
            "mkfs.ext4 failed for BACKUP partition: " + res.stderr.decode(errors="ignore")
        )


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

    # If no suitable partition is available try to prepare one automatically.
    if not backup_device:
        blank_dev = _find_blank_removable_device(lsblk_data)
        if blank_dev:
            try:
                _ensure_rescue_image_written(blank_dev["name"])
            except Exception as exc:
                BackupLog.objects.create(
                    level="error",
                    msg=(
                        "Can't prepare backup drive automatically.\n\n" +
                        str(exc)
                    ),
                )
            else:
                # Re-read block devices so that the freshly written partition
                # table appears in *lsblk* output.
                lsblk_data = json.loads(subprocess.check_output(
                    'lsblk --output NAME,HOTPLUG,MOUNTPOINT,FSTYPE,TYPE,LABEL,PARTLABEL  --json',
                    shell=True
                ).decode())['blockdevices']
                backup_device = get_backup_device(lsblk_data)

    if not backup_device:
        BackupLog.objects.create(
            level='warning',
            msg="Can't backup. No external BACKUP partition found and no blank removable device was available."
        )
        return

    if backup_device.get('partlabel'):
        sd_mountpoint = f"/media/{backup_device['partlabel']}"
    elif backup_device.get('label'):
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
    from simo.core.models import Instance
    from simo.core.middleware import drop_current_instance
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

    if not os.path.exists(device_backups_path):
        os.makedirs(device_backups_path)

    drop_current_instance()
    hub_meta = {
        'instances': [inst.name for inst in Instance.objects.all()]
    }
    with open(os.path.join(device_backups_path, 'hub_meta.json'), 'w') as f:
        f.write(json.dumps(hub_meta))

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

    # ------------------------------------------------------------------
    # Ensure that files stored on *separate* partitions – most importantly
    # the /boot (kernel & initrd images) and /boot/efi (EFI System
    # Partition) – are included in the snapshot.  Otherwise the rescue
    # procedure restores an empty /boot which leaves the system un-bootable
    # once GRUB hands over control to the (missing) kernel.
    #
    # We temporarily bind-mount those paths into the read-only snapshot so
    # that Borg treats them as regular directories residing on the same
    # filesystem tree.
    # ------------------------------------------------------------------

    bind_mounts = []
    for path in ("/boot", "/boot/efi"):
        target = os.path.join(snap_mount_point, path.lstrip("/"))
        # Create the mount-point inside the snapshot and bind-mount the live
        # directory if it exists.
        if os.path.ismount(path):
            os.makedirs(target, exist_ok=True)
            subprocess.run(["mount", "--bind", path, target], check=True)
            bind_mounts.append(target)

    # Directories that are safe to exclude – keep /boot out of this list!
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
        while shutil.disk_usage(sd_mountpoint).free < 20 * 1024 * 1024 * 1024:
            remove_folder = other_month_folders.pop()[0]
            print(f"REMOVE: {remove_folder}")
            shutil.rmtree(remove_folder)

    backup_command += f' {month_folder}::{get_random_string()} .'
    res = subprocess.run(
        backup_command, shell=True, cwd=snap_mount_point,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    # Unmount previously created bind-mounts (boot / boot/efi) *before*
    # removing the snapshot so that no busy references remain.
    for mnt in reversed(bind_mounts):
        subprocess.run(["umount", mnt])

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
