import os
import shutil
import hashlib

from django.conf import settings
from django.db import migrations, models
from simo.core.media_paths import instance_categories_upload_to, instance_private_files_upload_to


MAX_LEGACY_DB_FILEPATH_LENGTH = 100


def _shorten_filename(filename, *, max_length, seed):
    if not filename or max_length <= 0:
        return filename

    filename = os.path.basename(filename)
    if len(filename) <= max_length:
        return filename

    stem, ext = os.path.splitext(filename)
    digest = hashlib.sha1(seed.encode('utf-8')).hexdigest()[:8]

    # Prefer: <truncated-stem>-<hash8><ext>
    reserved = len(ext) + 1 + len(digest)
    if reserved >= max_length:
        # Extremely tight limit; keep extension if possible.
        room_for_hash = max_length - len(ext)
        if room_for_hash <= 0:
            return digest[:max_length]
        return f"{digest[:room_for_hash]}{ext}"

    stem_max = max_length - reserved
    return f"{stem[:stem_max]}-{digest}{ext}"


def _build_constrained_rel_path(prefix_parts, filename, *, seed, max_length=MAX_LEGACY_DB_FILEPATH_LENGTH):
    prefix = os.path.join(*prefix_parts)
    rel = os.path.join(prefix, filename)
    if len(rel) <= max_length:
        return rel

    max_filename_len = max_length - len(prefix) - 1
    safe_name = _shorten_filename(filename, max_length=max_filename_len, seed=seed)
    return os.path.join(prefix, safe_name)


def _move_file(old_rel, new_rel):
    if not old_rel or old_rel == new_rel:
        return
    old_abs = os.path.join(settings.MEDIA_ROOT, old_rel)
    new_abs = os.path.join(settings.MEDIA_ROOT, new_rel)
    if not os.path.exists(old_abs):
        return
    os.makedirs(os.path.dirname(new_abs), exist_ok=True)
    try:
        os.replace(old_abs, new_abs)
    except OSError:
        shutil.move(old_abs, new_abs)


def migrate_instance_media(apps, schema_editor):
    Category = apps.get_model('core', 'Category')
    PrivateFile = apps.get_model('core', 'PrivateFile')

    # Category.header_image: categories/<file> -> instances/<uid>/categories/<file>
    for cat in Category.objects.filter(header_image__isnull=False).exclude(header_image='').select_related('instance').iterator():
        old_rel = getattr(cat.header_image, 'name', '')
        if not old_rel:
            continue
        if old_rel.startswith('instances/'):
            continue
        instance_uid = getattr(getattr(cat, 'instance', None), 'uid', None)
        if not instance_uid:
            continue
        filename = os.path.basename(old_rel)
        new_rel = _build_constrained_rel_path(
            ['instances', str(instance_uid), 'categories'],
            filename,
            seed=f"category:{instance_uid}:{old_rel}",
        )
        _move_file(old_rel, new_rel)
        cat.header_image.name = new_rel
        cat.save(update_fields=['header_image'])

    # PrivateFile.file: private_files/<file> -> instances/<uid>/private_files/<file>
    # Resolve instance_uid via component -> zone -> instance
    for pf in PrivateFile.objects.filter(file__isnull=False).exclude(file='').select_related(
        'component__zone__instance'
    ).iterator():
        old_rel = getattr(pf.file, 'name', '')
        if not old_rel:
            continue
        if old_rel.startswith('instances/'):
            continue
        instance_uid = getattr(getattr(getattr(getattr(pf, 'component', None), 'zone', None), 'instance', None), 'uid', None)
        if not instance_uid:
            continue
        filename = os.path.basename(old_rel)
        new_rel = _build_constrained_rel_path(
            ['instances', str(instance_uid), 'private_files'],
            filename,
            seed=f"privatefile:{instance_uid}:{old_rel}",
        )
        _move_file(old_rel, new_rel)
        pf.file.name = new_rel
        pf.save(update_fields=['file'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0053_remove_legacy_methods_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='category',
            name='header_image',
            field=models.ImageField(
                blank=True,
                help_text='Will be cropped down to: 830x430',
                null=True,
                upload_to=instance_categories_upload_to,
            ),
        ),
        migrations.AlterField(
            model_name='privatefile',
            name='file',
            field=models.FileField(upload_to=instance_private_files_upload_to),
        ),
        migrations.RunPython(migrate_instance_media, reverse_code=migrations.RunPython.noop),
    ]
