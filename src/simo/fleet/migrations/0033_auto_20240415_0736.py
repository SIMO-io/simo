# Generated by Django 3.2.9 on 2024-04-15 07:36

from django.db import migrations

def create_objects(apps, schema_editor):
    I2CInterface = apps.get_model("fleet", "I2CInterface")
    Interface = apps.get_model("fleet", "Interface")
    for i2c_i in I2CInterface.objects.filter(no__gt=0):
        Interface.objects.create(
            colonel=i2c_i.colonel, type='i2c',
            pin_a=i2c_i.scl_pin, pin_b=i2c_i.sda_pin
        )


def delete_objects(apps, schema_editor):
    Interface = apps.get_model("fleet", "Interface")
    Interface.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0032_auto_20240415_0736'),
    ]

    operations = [
        migrations.RunPython(create_objects, delete_objects),
    ]