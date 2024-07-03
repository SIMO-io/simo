import os
from django.core.files.storage import FileSystemStorage as OrgFileSystemStorage
from django.conf import settings


class OverwriteStorage(OrgFileSystemStorage):

    def get_available_name(self, name, max_length=None):
        if self.exists(name):
            os.remove(os.path.join(settings.MEDIA_ROOT, name))
        return name
