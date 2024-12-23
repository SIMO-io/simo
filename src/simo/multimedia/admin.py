import librosa
from datetime import timedelta
from django.contrib import admin
from .models import Sound
from .forms import SoundModelForm


@admin.register(Sound)
class SoundAdmin(admin.ModelAdmin):
    list_display = 'id', 'name', 'file', 'duration_display', 'date_uploaded'
    search_fields = 'name', 'file'
    list_display_links = 'id', 'name',
    form = SoundModelForm
    readonly_fields = 'duration_display',

    def duration_display(self, obj=None):
        if obj and obj.duration != None:
            return str(timedelta(seconds=obj.duration))

    duration_display.short_description = 'duration'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # need to keep it here as using admin interface skips post_save signals
        try:
            obj.duration = int(
                librosa.core.get_duration(
                    sr=22050, filename=obj.file.path
                )
            )
        except:
            pass
        else:
            obj.save()


