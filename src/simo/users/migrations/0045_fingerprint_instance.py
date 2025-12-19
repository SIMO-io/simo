import re

from django.db import migrations, models
import django.db.models.deletion


def backfill_fingerprint_instance(apps, schema_editor):
    Fingerprint = apps.get_model('users', 'Fingerprint')
    Component = apps.get_model('core', 'Component')

    pattern = re.compile(r'^ttlock-(?P<component_id>\d+)-')

    for fp in Fingerprint.objects.filter(instance__isnull=True).iterator():
        match = pattern.match(fp.value or '')
        if not match:
            continue
        component_id = int(match.group('component_id'))
        component = Component.objects.filter(id=component_id).select_related(
            'zone__instance'
        ).first()
        if not component:
            continue
        try:
            fp.instance_id = component.zone.instance_id
            fp.save(update_fields=['instance'])
        except Exception:
            continue


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0053_remove_legacy_methods_fields'),
        ('users', '0044_permissionsrole_is_person'),
    ]

    operations = [
        migrations.AddField(
            model_name='fingerprint',
            name='instance',
            field=models.ForeignKey(
                blank=True,
                help_text='Owning smart home instance (tenant).',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='core.instance',
            ),
        ),
        migrations.RunPython(
            backfill_fingerprint_instance,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

