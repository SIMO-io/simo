# Generated by Django 4.2.10 on 2024-03-22 11:30

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0024_fingerprint'),
    ]

    operations = [
        migrations.RenameField(
            model_name='fingerprint',
            old_name='name',
            new_name='type',
        ),
        migrations.RemoveField(
            model_name='fingerprint',
            name='is_valid',
        ),
    ]