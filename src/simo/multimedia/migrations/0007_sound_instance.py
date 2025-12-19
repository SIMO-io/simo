from django.db import migrations, models
import django.db.models.deletion


def backfill_sound_instance(apps, schema_editor):
    Sound = apps.get_model('multimedia', 'Sound')
    Component = apps.get_model('core', 'Component')

    for sound in Sound.objects.filter(instance__isnull=True).iterator():
        component = Component.objects.filter(
            config__sound_id=sound.id
        ).select_related('zone__instance').first()
        if not component:
            continue
        try:
            sound.instance_id = component.zone.instance_id
            sound.save(update_fields=['instance'])
        except Exception:
            continue


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0053_remove_legacy_methods_fields'),
        ('multimedia', '0006_remove_sound_length_sound_duration'),
    ]

    operations = [
        migrations.AddField(
            model_name='sound',
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
            backfill_sound_instance,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
