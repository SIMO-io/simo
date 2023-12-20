import librosa
import os
from django.core.files.storage import FileSystemStorage
from django import forms
from .models import Sound


class SoundModelForm(forms.ModelForm):

    class Meta:
        model = Sound
        fields = '__all__'
