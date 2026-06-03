from django.db import migrations

import simo.core.model_fields


def _normalize_email(value):
    if isinstance(value, str):
        return value.strip().lower()
    return value


def _assert_unique_normalized(model, field_name):
    seen = {}
    duplicates = []
    for pk, value in model.objects.values_list('pk', field_name).iterator():
        normalized = _normalize_email(value)
        if not normalized:
            continue
        other_pk = seen.get(normalized)
        if other_pk is None:
            seen[normalized] = pk
            continue
        duplicates.append((other_pk, pk, normalized))
    if duplicates:
        formatted = ', '.join(
            f'{value}: {pk1}/{pk2}' for pk1, pk2, value in duplicates[:10]
        )
        raise RuntimeError(
            f'Cannot lowercase {model._meta.label}.{field_name}; '
            f'found case-insensitive duplicates: {formatted}'
        )


def lowercase_user_emails(apps, schema_editor):
    User = apps.get_model('users', 'User')
    InstanceInvitation = apps.get_model('users', 'InstanceInvitation')

    _assert_unique_normalized(User, 'email')

    for pk, value in User.objects.values_list('pk', 'email').iterator():
        normalized = _normalize_email(value)
        if normalized != value:
            User.objects.filter(pk=pk).update(email=normalized)

    for pk, value in InstanceInvitation.objects.values_list('pk', 'to_email').iterator():
        normalized = _normalize_email(value)
        if normalized != value:
            InstanceInvitation.objects.filter(pk=pk).update(to_email=normalized)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0046_user_media_uid_avatar_path'),
    ]

    operations = [
        migrations.RunPython(lowercase_user_emails, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='instanceinvitation',
            name='to_email',
            field=simo.core.model_fields.LowercaseEmailField(blank=True, max_length=254, null=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='email',
            field=simo.core.model_fields.LowercaseEmailField(max_length=254, unique=True, verbose_name='email address'),
        ),
    ]
