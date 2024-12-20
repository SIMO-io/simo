# Generated by Django 4.2.10 on 2024-12-03 09:30

from django.db import migrations


def forwards_func(apps, schema_editor):
    Component = apps.get_model("core", "Component")

    for comp in Component.objects.filter(
        controller_uid='simo.fleet.controllers.MPC9808TempSensor'
    ):
        comp.controller_uid = 'simo.fleet.controllers.MCP9808TempSensor'
        comp.save()


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0042_auto_20241120_1028'),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func, elidable=True),
    ]
