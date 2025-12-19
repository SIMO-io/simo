import os

from simo.core.utils.helpers import get_random_string


MEDIA_UID_SIZE = 16


def get_user_media_uid():
    return get_random_string(MEDIA_UID_SIZE)


def user_avatar_upload_to(instance, filename):
    media_uid = getattr(instance, 'media_uid', None) or 'unknown'
    return os.path.join('avatars', str(media_uid), filename)


def instance_categories_upload_to(instance, filename):
    try:
        instance_uid = instance.instance.uid
    except Exception:
        instance_uid = 'unknown'
    return os.path.join('instances', str(instance_uid), 'categories', filename)


def instance_private_files_upload_to(instance, filename):
    try:
        instance_uid = instance.component.zone.instance.uid
    except Exception:
        instance_uid = 'unknown'
    return os.path.join('instances', str(instance_uid), 'private_files', filename)

