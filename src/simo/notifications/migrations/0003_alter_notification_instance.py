# Generated by Django 4.2.10 on 2024-11-04 10:01

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0043_alter_category_instance_alter_instance_timezone_and_more'),
        ('notifications', '0002_notification_instance'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='instance',
            field=models.ForeignKey(limit_choices_to={'is_active': True}, on_delete=django.db.models.deletion.CASCADE, to='core.instance'),
        ),
    ]
