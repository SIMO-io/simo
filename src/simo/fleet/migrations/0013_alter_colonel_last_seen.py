# Generated by Django 3.2.9 on 2022-06-10 11:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0012_colonel_logs_stream'),
    ]

    operations = [
        migrations.AlterField(
            model_name='colonel',
            name='last_seen',
            field=models.DateTimeField(db_index=True, editable=False, null=True),
        ),
    ]