# Generated by Django 3.2.9 on 2024-05-06 11:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0027_permissionsrole_can_manage_components'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='permissionsrole',
            name='can_manage_components',
        ),
        migrations.AddField(
            model_name='permissionsrole',
            name='is_owner',
            field=models.BooleanField(default=False, help_text='Can manage zones, basic component parametersand other things via SIMO.io app, but is not yet allowed to perform any serious system changes, like superusers can.'),
        ),
    ]