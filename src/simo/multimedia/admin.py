import librosa
from datetime import timedelta
from django.contrib import admin
from .models import Sound
from .forms import SoundModelForm


@admin.register(Sound)
class SoundAdmin(admin.ModelAdmin):
    list_display = 'id', 'name', 'slug', 'file', 'length_display'
    search_fields = 'name', 'slug', 'file'
    prepopulated_fields = {"slug": ["name"]}
    list_display_links = 'id', 'name', 'slug'
    form = SoundModelForm
    readonly_fields = 'length_display',

    def length_display(self, obj=None):
        if obj and obj.length != None:
            return str(timedelta(seconds=obj.length))

    length_display.short_description = 'length'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        try:
            obj.length = int(
                librosa.core.get_duration(
                    sr=22050, filename=obj.file.path
                )
            )
        except:
            pass
        else:
            obj.save()


