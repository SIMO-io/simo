# Generated by Django 3.2.9 on 2023-10-04 11:13

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_auto_20231004_1113'),
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='instance',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, to='core.instance'),
            preserve_default=False,
        ),
    ]
