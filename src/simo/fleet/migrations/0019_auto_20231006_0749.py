# Generated by Django 3.2.9 on 2023-10-06 07:49

from django.db import migrations


def forwards_func(apps, schema_editor):
    Instance = apps.get_model("core", "Instance")
    Colonel = apps.get_model('fleet', "Colonel")
    Colonel.objects.all().update(
        instance=Instance.objects.all().first()
    )


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0018_colonel_instance'),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_func, elidable=True),
    ]
