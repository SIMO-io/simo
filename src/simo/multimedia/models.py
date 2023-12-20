import os
from django.db import models
from django.core.files.storage import FileSystemStorage
from django.conf import settings


class Sound(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    slug = models.SlugField()
    file = models.FileField(
        upload_to='sounds', storage=FileSystemStorage(
            location=os.path.join(settings.VAR_DIR, 'public_media'),
            base_url='/public_media/'
        )
    )
    note = models.TextField(null=True, blank=True)
    length = models.PositiveIntegerField(
        editable=False, default=0, help_text='Sound length in seconds'
    )

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return self.file.url
