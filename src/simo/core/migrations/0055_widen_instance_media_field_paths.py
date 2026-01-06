from django.db import migrations, models

from simo.core.media_paths import instance_categories_upload_to, instance_private_files_upload_to


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0054_instance_scoped_media_paths'),
    ]

    operations = [
        migrations.AlterField(
            model_name='category',
            name='header_image',
            field=models.ImageField(
                blank=True,
                help_text='Will be cropped down to: 830x430',
                max_length=255,
                null=True,
                upload_to=instance_categories_upload_to,
            ),
        ),
        migrations.AlterField(
            model_name='privatefile',
            name='file',
            field=models.FileField(max_length=255, upload_to=instance_private_files_upload_to),
        ),
    ]

