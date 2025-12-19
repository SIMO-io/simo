import os
import random
import shutil
import string

from django.conf import settings
from django.db import migrations, models
from easy_thumbnails.fields import ThumbnailerImageField
from simo.core.media_paths import get_user_media_uid, user_avatar_upload_to


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


def _rand_uid(size=16):
    chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(size))


def backfill_user_media_uid_and_move_avatars(apps, schema_editor):
    User = apps.get_model('users', 'User')

    used = set(
        User.objects.exclude(media_uid__isnull=True)
        .exclude(media_uid='')
        .values_list('media_uid', flat=True)
    )

    for user in User.objects.all().iterator():
        if not user.media_uid:
            media_uid = _rand_uid()
            while media_uid in used:
                media_uid = _rand_uid()
            used.add(media_uid)
            user.media_uid = media_uid
            user.save(update_fields=['media_uid'])

        old_rel = getattr(user.avatar, 'name', '')
        if not old_rel:
            continue
        # already partitioned: avatars/<media_uid>/...
        parts = [p for p in old_rel.split('/') if p]
        if len(parts) >= 3 and parts[0] == 'avatars':
            continue
        filename = os.path.basename(old_rel)
        new_rel = f'avatars/{user.media_uid}/{filename}'
        _move_file(old_rel, new_rel)
        user.avatar.name = new_rel
        user.save(update_fields=['avatar'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0045_fingerprint_instance'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='media_uid',
            field=models.CharField(
                blank=True,
                null=True,
                db_index=True,
                max_length=16,
                unique=True,
                help_text='Non-secret identifier used for media path partitioning.',
            ),
        ),
        migrations.RunPython(
            backfill_user_media_uid_and_move_avatars,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='user',
            name='media_uid',
            field=models.CharField(
                db_index=True,
                default=get_user_media_uid,
                help_text='Non-secret identifier used for media path partitioning.',
                max_length=16,
                unique=True,
                null=False,
            ),
        ),
        migrations.AlterField(
            model_name='user',
            name='avatar',
            field=ThumbnailerImageField(
                blank=True,
                help_text='Comes from SIMO.io',
                null=True,
                upload_to=user_avatar_upload_to,
            ),
        ),
    ]
