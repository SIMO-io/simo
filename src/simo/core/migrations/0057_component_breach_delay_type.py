from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0056_component_breach_delay'),
    ]

    operations = [
        migrations.AddField(
            model_name='component',
            name='breach_delay_type',
            field=models.CharField(
                max_length=20,
                default='continuous',
                choices=[('continuous', 'Continuous'), ('accumulated', 'Accumulated')],
                help_text=(
                    'Continuous requires an uninterrupted alarm. Accumulated breaches '
                    'after the delay from the first activation, even if the alarm clears.'
                ),
            ),
        ),
    ]
