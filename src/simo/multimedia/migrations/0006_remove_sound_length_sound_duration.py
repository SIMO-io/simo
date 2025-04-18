# Generated by Django 4.2.10 on 2024-12-22 07:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('multimedia', '0005_remove_sound_slug_sound_date_uploaded'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='sound',
            name='length',
        ),
        migrations.AddField(
            model_name='sound',
            name='duration',
            field=models.PositiveIntegerField(default=0, editable=False, help_text='Sound duration in seconds'),
        ),
    ]
