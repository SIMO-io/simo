# Generated by Django 4.2.10 on 2024-06-26 12:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0039_instance_is_active_alter_instance_timezone'),
    ]

    operations = [
        migrations.AlterField(
            model_name='instance',
            name='name',
            field=models.CharField(db_index=True, max_length=100),
        ),
    ]
