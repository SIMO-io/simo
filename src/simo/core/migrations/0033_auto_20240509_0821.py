# Generated by Django 3.2.9 on 2024-05-09 08:21

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0032_auto_20240506_0834'),
    ]

    operations = [
        migrations.AddField(
            model_name='component',
            name='last_modified',
            field=models.DateTimeField(auto_now_add=True, db_index=True, default=django.utils.timezone.now, help_text='Last time component was modified.'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='component',
            name='last_change',
            field=models.DateTimeField(auto_now_add=True, help_text='Last time component state was changed.', null=True),
        ),
    ]
