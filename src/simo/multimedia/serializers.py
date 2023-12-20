from rest_framework import serializers
from .models import Sound


class SoundSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Sound
        fields = 'id', 'name', 'slug', 'length', 'url'


    def get_url(self, obj):
        return self.context['request'].build_absolute_uri(
            obj.file.url
        )
