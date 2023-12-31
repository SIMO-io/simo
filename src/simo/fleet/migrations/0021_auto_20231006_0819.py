# Generated by Django 3.2.9 on 2023-10-06 08:19

from django.db import migrations


def forwards_func(apps, schema_editor):
    Instance = apps.get_model("core", "Instance")
    InstanceOptions = apps.get_model('fleet', 'InstanceOptions')

    for inst in Instance.objects.all():
        InstanceOptions.objects.get_or_create(instance=inst)

def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0020_instanceoptions'),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func, elidable=True),
    ]
