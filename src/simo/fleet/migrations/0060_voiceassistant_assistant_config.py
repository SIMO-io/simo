from django.db import migrations


def migrate_voice_to_assistant(apps, schema_editor):
    Component = apps.get_model('core', 'Component')

    qs = Component.objects.filter(controller_uid='simo.fleet.controllers.VoiceAssistant')
    for comp in qs.iterator():
        cfg = dict(comp.config or {})
        if cfg.get('assistant'):
            continue
        voice = (cfg.get('voice') or '').strip().lower()
        if voice == 'male':
            assistant = 'kovan'
        else:
            assistant = 'alora'
        cfg['assistant'] = assistant
        comp.config = cfg
        comp.save(update_fields=['config'])


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0059_sentinel_pairing_request'),
    ]

    operations = [
        migrations.RunPython(migrate_voice_to_assistant, migrations.RunPython.noop),
    ]

