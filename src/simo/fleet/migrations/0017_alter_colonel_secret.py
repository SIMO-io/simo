# Generated by Django 3.2.9 on 2023-10-02 06:36

from django.db import migrations, models
import simo.fleet.models


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0016_auto_20220704_0840'),
    ]

    operations = [
        migrations.AlterField(
            model_name='colonel',
            name='secret',
            field=models.CharField(blank=True, db_index=True, default=simo.fleet.models.get_new_secret, max_length=100),
        ),
    ]
