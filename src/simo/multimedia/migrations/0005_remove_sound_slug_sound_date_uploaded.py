# Generated by Django 4.2.10 on 2024-12-11 14:14

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('multimedia', '0004_auto_20231023_1055'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='sound',
            name='slug',
        ),
        migrations.AddField(
            model_name='sound',
            name='date_uploaded',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]