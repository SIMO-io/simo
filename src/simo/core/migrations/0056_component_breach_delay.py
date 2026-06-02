from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0055_widen_instance_media_field_paths'),
    ]

    operations = [
        migrations.AddField(
            model_name='component',
            name='breach_delay',
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text='Delay breach transition by this many seconds. Leave empty or use 0 for immediate breach.',
                validators=[MinValueValidator(0), MaxValueValidator(600)],
            ),
        ),
    ]
