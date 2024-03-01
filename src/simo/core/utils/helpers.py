import string
import random
import functools
import re
import socket
import operator
import math
import simo
from django.db import models
from simo.conf import dynamic_settings


class classproperty(property):
    def __get__(self, cls, owner):
        return self.fget.__get__(None, owner)()


def get_random_string(
    size=20, chars=string.ascii_uppercase + string.ascii_lowercase + string.digits
):
    return ''.join(random.choice(chars) for x in range(size))



def is_hex_color(input_string):
    HEX_COLOR_REGEX = r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{8})$'
    regexp = re.compile(HEX_COLOR_REGEX)
    if regexp.search(input_string):
        return True
    return False



def heat_index(temp, hum, fahrenheit=True):
    if not fahrenheit:
        temp = round((temp * 9 / 5) + 32, 1)
    hi = temp
    if temp > 40:

        hitemp = 61.0 + ((temp - 68.0) * 1.2) + (hum * 0.094)

        fptemp = temp

        hifinal = 0.5 * (fptemp + hitemp)

        if (hifinal > 79.0):
            hi = -42.379+2.04901523 * temp+10.14333127 * hum-0.22475541 * temp * hum-6.83783 * (pow(10, -3)) * (pow(temp, 2))-5.481717 * (pow(10, -2)) * (pow(hum, 2))+1.22874 * (pow(10, -3)) * (pow(temp, 2)) * hum+8.5282 * (pow(10, -4)) * temp * (pow(hum, 2))-1.99 * (pow(10, -6)) * (pow(temp, 2)) * (pow(hum, 2))
            if ((hum <= 13) and (temp >= 80.0) and (temp <= 112.0)):
                adj1 = (13.0-hum) / 4.0
                adj2 = math.sqrt((17.0-abs(temp-95.0)) / 17.0)
                adj = adj1 * adj2
                hi = hi - adj

            elif ((hum > 85.0) and (temp >= 80.0) and (temp <= 87.0)):
                adj1 = (hum-85.0) / 10.0
                adj2 = (87.0-temp) / 5.0
                adj = adj1 * adj2
                hi = hi + adj


        else:
            hi = hifinal

    hi = round(hi, 1)

    if not fahrenheit:
        hi = round((hi - 32) * 5/9, 1)
    return hi


def get_self_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def search_queryset(queryset, search_term, search_fields):
    orm_lookups = ["%s__icontains" % search_field
                   for search_field in search_fields]
    for bit in search_term.split():
        or_queries = [models.Q(**{orm_lookup: bit})
                      for orm_lookup in orm_lookups]
        queryset = queryset.filter(functools.reduce(operator.or_, or_queries))
    return queryset


def is_update_available(including_major=False):
    major_available = 0
    minor_available = 0
    patch_available = 0
    major_current = 9999999999
    minor_current = 9999999999
    patch_current = 9999999999
    version_available = dynamic_settings['core__latest_version_available']
    try:
        major_available, minor_available, patch_available = [
            int(n) for n in version_available.split('.')
        ]
    except:
        pass
    try:
        major_current, minor_current, patch_current = [
            int(n) for n in simo.__version__.split('.')
        ]
    except:
        pass
    if major_available > major_current:
        if including_major:
            return version_available
        else:
            return None
    if major_available == major_current and minor_available > minor_current:
        return version_available
    if major_available == major_current and minor_available == minor_current \
    and patch_available > patch_current:
        return version_available
