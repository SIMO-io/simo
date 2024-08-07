# Generated by Django 4.2.10 on 2024-03-06 11:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0029_alter_i2cinterface_scl_pin_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='colonelpin',
            name='label',
            field=models.CharField(db_index=True, default='', max_length=200),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='colonel',
            name='type',
            field=models.CharField(choices=[('4-relays', '4 Relay'), ('ample-wall', 'Ample Wall')], default='ample-wall', max_length=20),
        ),
    ]
