# Generated by Django 3.2.9 on 2024-05-21 08:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0035_remove_instance_share_location'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='category',
            name='header_image_last_change',
        ),
        migrations.AddField(
            model_name='category',
            name='last_modified',
            field=models.DateTimeField(auto_now=True),
        ),
    ]