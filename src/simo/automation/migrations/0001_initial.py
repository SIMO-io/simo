# Generated by Django 4.2.10 on 2024-11-27 07:40

from django.db import migrations


def forwards_func(apps, schema_editor):
    Component = apps.get_model("core", "Component")
    Gateway = apps.get_model('core', "Gateway")

    automation, new = Gateway.objects.get_or_create(
        type='simo.automation.gateways.AutomationsGatewayHandler'
    )

    for script in Component.objects.filter(
        controller_uid__in=(
            'simo.generic.controllers.PresenceLighting',
            'simo.generic.controllers.Script',
        )
    ):
        script.controller_uid = script.controller_uid.replace(
            'simo.generic', 'simo.automation'
        )
        script.gateway = automation
        script.save()


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('generic', '0002_auto_20241126_0726'),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func, elidable=True),
    ]