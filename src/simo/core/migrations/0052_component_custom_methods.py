from django.db import migrations, models


DEFAULT_CUSTOM_METHODS = '''
def translate(value, occasion):
    """
        Adjust this to make value translations before value is
        set on to a component and before it is sent to a device 
        from your SIMO.io smart home instance.
    """
    if occasion == 'before-set':
        return value
    else:  # 'before-send'
        return value


def is_in_alarm(self):
    return bool(self.value)
'''


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0051_instance_ai_memory'),
    ]

    operations = [
        migrations.AddField(
            model_name='component',
            name='custom_methods',
            field=models.TextField(
                blank=True,
                default=DEFAULT_CUSTOM_METHODS,
                help_text=(
                    "Add your custom translate(value, occasion) and optional instance"
                    " methods. This supersedes both 'value_translation' and"
                    " 'instance_methods'."
                ),
            ),
        ),
    ]

