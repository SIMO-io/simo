# Generated by Django 3.2.9 on 2023-10-04 11:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_zone_instance'),
    ]

    operations = [
        migrations.AddField(
            model_name='instance',
            name='slug',
            field=models.CharField(
                db_index=True, default='', max_length=100
            ), preserve_default=False,
        ),
        migrations.AlterField(
            model_name='component',
            name='last_change',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AlterField(
            model_name='instance',
            name='name',
            field=models.CharField(db_index=True, max_length=100, unique=True),
        ),
        migrations.AlterField(
            model_name='instance',
            name='uid',
            field=models.CharField(help_text='Issued by SIMO.io', max_length=50, unique=True),
        ),
    ]