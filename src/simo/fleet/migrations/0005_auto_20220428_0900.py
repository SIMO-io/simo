# Generated by Django 3.2.9 on 2022-04-28 09:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_alter_component_subcomponents'),
        ('fleet', '0004_auto_20220422_0818'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='colonel',
            name='socket_connected',
        ),
        migrations.AddField(
            model_name='colonel',
            name='components',
            field=models.ManyToManyField(editable=False, to='core.Component'),
        ),
        migrations.AddField(
            model_name='colonel',
            name='firmware_download_token',
            field=models.CharField(db_index=True, editable=False, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='colonel',
            name='occupied_pins',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]