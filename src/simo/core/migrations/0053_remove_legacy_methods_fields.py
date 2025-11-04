from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0052_component_custom_methods'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='component',
            name='value_translation',
        ),
        migrations.RemoveField(
            model_name='component',
            name='instance_methods',
        ),
    ]

