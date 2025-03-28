# Generated by Django 4.2.10 on 2024-12-13 09:44

import django.core.files.storage
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0047_alter_component_value_translation'),
    ]

    operations = [
        migrations.CreateModel(
            name='PublicFile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(storage=django.core.files.storage.FileSystemStorage(base_url='/public_media/', location='/home/simanas/Projects/SIMO/_var/public_media'), upload_to='public_files')),
                ('date_uploaded', models.DateTimeField(auto_now_add=True)),
                ('meta', models.JSONField(default=dict)),
                ('component', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='public_files', to='core.component')),
            ],
        ),
        migrations.CreateModel(
            name='PrivateFile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='private_files')),
                ('date_uploaded', models.DateTimeField(auto_now_add=True)),
                ('meta', models.JSONField(default=dict)),
                ('component', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='private_files', to='core.component')),
            ],
        ),
    ]
