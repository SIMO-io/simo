import os
from django.contrib.staticfiles.storage import StaticFilesStorage as OrgStaticFilesStorage
from django.core.files.storage import FileSystemStorage as OrgFileSystemStorage
from django.conf import settings
from simo.core.middleware import get_current_request
from simo.conf import dynamic_settings


class SIMOProxyMixin():

    def url(self, name):
        url = super().url(name)
        request = get_current_request()
        if request and request.META.get('HTTP_HOST', '').endswith('.simo.io'):
            return dynamic_settings['core__remote_http'] + url
        return url


class ProxyingStaticFilesStorage(SIMOProxyMixin, OrgStaticFilesStorage):
    pass


class ProxyingFileSystemStorage(SIMOProxyMixin, OrgFileSystemStorage):
    pass


class OverwriteStorage(ProxyingFileSystemStorage):

    def get_available_name(self, name, max_length=None):
        if self.exists(name):
            os.remove(os.path.join(settings.MEDIA_ROOT, name))
        return name
