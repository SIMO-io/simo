# Generated by Django 3.2.9 on 2022-07-07 14:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_alter_component_change_init_to'),
    ]

    operations = [
        migrations.AlterField(
            model_name='componenthistory',
            name='date',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AlterField(
            model_name='componenthistory',
            name='type',
            field=models.CharField(choices=[('value', 'Value'), ('security', 'Security')], db_index=True, max_length=50),
        ),
    ]