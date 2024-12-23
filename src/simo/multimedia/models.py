import os, librosa
from django.urls import reverse
from django.db import models
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.files.storage import FileSystemStorage
from django.conf import settings


class Sound(models.Model):
    name = models.CharField(max_length=100, db_index=True)
    file = models.FileField(
        upload_to='sounds', storage=FileSystemStorage(
            location=os.path.join(settings.VAR_DIR, 'public_media'),
            base_url='/public_media/'
        )
    )
    note = models.TextField(null=True, blank=True)
    duration = models.PositiveIntegerField(
        editable=False, default=0, help_text='Sound duration in seconds'
    )
    date_uploaded = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return self.file.url

    def stream_url(self):
        return reverse('sound-stream', kwargs={'sound_id': self.id})


@receiver(post_save, sender=Sound)
def determine_duration(sender, instance, created, **kwargs):
    if not instance.duration:
        instance.duration = int(
            librosa.core.get_duration(
                sr=22050, filename=instance.file.path
            )
        )
        instance.save()

