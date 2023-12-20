from django.urls import get_script_prefix
from django.http import HttpResponseRedirect as OrgHttpResponseRedirect


class HttpResponseRedirect(OrgHttpResponseRedirect):

    @property
    def url(self):
        prefix = get_script_prefix()

        if self['Location'].startswith('http'):
            return self['Location']

        if self['Location'].startswith(prefix):
            return self['Location']

        return prefix[:-1] + self['Location']
