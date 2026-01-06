import os
import hashlib

from simo.core.utils.helpers import get_random_string


MEDIA_UID_SIZE = 16
INSTANCE_FILEFIELD_MAX_LENGTH = 255


def _shorten_filename(filename, *, max_length, seed):
    filename = os.path.basename(filename or '')
    if not filename or len(filename) <= max_length:
        return filename

    stem, ext = os.path.splitext(filename)
    digest = hashlib.sha1(seed.encode('utf-8')).hexdigest()[:8]

    # Prefer: <truncated-stem>-<hash8><ext>
    reserved = len(ext) + 1 + len(digest)
    if reserved >= max_length:
        room_for_hash = max_length - len(ext)
        if room_for_hash <= 0:
            return digest[:max_length]
        return f"{digest[:room_for_hash]}{ext}"

    stem_max = max_length - reserved
    return f"{stem[:stem_max]}-{digest}{ext}"


def _build_constrained_rel_path(prefix_parts, filename, *, seed, max_length):
    prefix = os.path.join(*prefix_parts)
    rel = os.path.join(prefix, os.path.basename(filename or ''))
    if len(rel) <= max_length:
        return rel

    max_filename_len = max_length - len(prefix) - 1
    safe_name = _shorten_filename(filename, max_length=max_filename_len, seed=seed)
    return os.path.join(prefix, safe_name)


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

    category_id = getattr(instance, 'pk', None) or getattr(instance, 'id', None)
    seed = f"category:{instance_uid}:{category_id}:{filename}"
    if category_id is None:
        seed = f"{seed}:{get_random_string(12)}"

    return _build_constrained_rel_path(
        ['instances', str(instance_uid), 'categories'],
        filename,
        seed=seed,
        max_length=INSTANCE_FILEFIELD_MAX_LENGTH,
    )


def instance_private_files_upload_to(instance, filename):
    try:
        instance_uid = instance.component.zone.instance.uid
    except Exception:
        instance_uid = 'unknown'

    privatefile_id = getattr(instance, 'pk', None) or getattr(instance, 'id', None)
    component_id = getattr(getattr(instance, 'component', None), 'pk', None) or getattr(getattr(instance, 'component', None), 'id', None)
    seed = f"privatefile:{instance_uid}:{component_id}:{privatefile_id}:{filename}"
    if privatefile_id is None:
        seed = f"{seed}:{get_random_string(12)}"

    return _build_constrained_rel_path(
        ['instances', str(instance_uid), 'private_files'],
        filename,
        seed=seed,
        max_length=INSTANCE_FILEFIELD_MAX_LENGTH,
    )
