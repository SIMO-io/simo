# Generated by Django 4.2.10 on 2024-11-04 10:01

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0043_alter_category_instance_alter_instance_timezone_and_more'),
        ('fleet', '0040_alter_colonel_pwm_frequency'),
    ]

    operations = [
        migrations.AlterField(
            model_name='colonel',
            name='instance',
            field=models.ForeignKey(default=1, limit_choices_to={'is_active': True}, on_delete=django.db.models.deletion.CASCADE, related_name='colonels', to='core.instance'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='instanceoptions',
            name='instance',
            field=models.OneToOneField(limit_choices_to={'is_active': True}, on_delete=django.db.models.deletion.CASCADE, related_name='fleet_options', to='core.instance'),
        ),
        migrations.AlterField(
            model_name='interface',
            name='type',
            field=models.CharField(blank=True, choices=[('i2c', 'I2C'), ('dali', 'DALI')], max_length=20, null=True),
        ),
    ]