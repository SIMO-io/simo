import re, os
from django.http import Http404
from django.conf import settings
from wsgiref.util import FileWrapper
from django.shortcuts import get_object_or_404
from django.http import StreamingHttpResponse
from dal import autocomplete
from simo.core.utils.helpers import search_queryset
from .models import Sound


class SoundAutocomplete(autocomplete.Select2QuerySetView):

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            raise Http404()

        qs = Sound.objects.all()

        if self.request.GET.get('value'):
            qs = qs.filter(pk__in=self.request.GET['value'].split(','))
        elif self.q:
            qs = search_queryset(qs, self.q, ('name', 'slug'))
        return qs





def file_iterator(file_path, chunk_size=8192, offset=0, length=None):
    with open(file_path, "rb") as f:
        f.seek(offset, os.SEEK_SET)
        remaining = length
        while True:
            bytes_length = (
                chunk_size
                if remaining is None
                else min(remaining, chunk_size)
            )
            data = f.read(bytes_length)
            if not data:
                break
            if remaining:
                remaining -= len(data)
            yield data



def sound_stream(request, sound_id):
    sound = get_object_or_404(Sound, id=sound_id)
    path = sound.file.path
    content_type = "audio/" + path.split('.')[-1]

    range_header = request.META.get("HTTP_RANGE", "").strip()
    RANGE_RE = re.compile(r"bytes\s*=\s*(\d+)\s*-\s*(\d*)", re.I)
    range_match = RANGE_RE.match(range_header)
    size = os.path.getsize(path)

    if range_match:
        print(f"RANGE HEADER: {range_header}")
        first_byte, last_byte = range_match.groups()
        first_byte = int(first_byte) if first_byte else 0
        last_byte = (
                first_byte + 1024 * 1024 * 8
        )  # The max volume of the response body is 8M per piece
        if last_byte >= size:
            last_byte = size - 1
        length = last_byte - first_byte + 1
        response = StreamingHttpResponse(
            file_iterator(path, offset=first_byte, length=length),
            status=206,
            content_type=content_type,
        )
        response["Content-Range"] = f"bytes {first_byte}-{last_byte}/{size}"

    else:
        response = StreamingHttpResponse(
            FileWrapper(open(path, "rb")), content_type=content_type
        )
    response["Accept-Ranges"] = "bytes"
    return response