# Generated by Django 3.2.9 on 2023-10-04 11:13

from django.db import migrations
from django.utils.text import slugify


def forwards_func(apps, schema_editor):

    Instance = apps.get_model("core", "Instance")
    for instance in Instance.objects.all():
        instance.slug = slugify(instance.name)
        instance.save()


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_auto_20231004_1113'),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func, elidable=True),
    ]
