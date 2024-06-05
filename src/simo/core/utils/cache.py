from django.conf import settings
from django.core.cache import caches


def get_cached_data(
    key, rebuild_function, cache_time=None, cache_name='default', rebuild=False
):
    data = caches[cache_name].get(key, 'NONE!')
    if data == 'NONE!' or rebuild:
        print(f"{cache_name} cache rebuild: {rebuild_function.__name__}()")
        data = rebuild_function()
        if not cache_time:
            cache_time = settings.CACHES[cache_name]['TIMEOUT']
        caches[cache_name].set(key, data, cache_time)
    return data