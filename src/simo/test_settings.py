"""Test settings for SIMO.

Uses the normal SIMO settings but swaps out external dependencies (Redis cache,
URLs module) so tests can run against a temporary PostgreSQL test DB.
"""

from .settings import *  # noqa

import os


# Use package URLs (the hub deployment uses a top-level `urls.py`).
ROOT_URLCONF = 'simo.urls'


# Minimal SECRET_KEY for tests.
SECRET_KEY = 'simo-test-secret-key'


# Use a writable filesystem layout for migrations that create files.
BASE_DIR = os.environ.get('SIMO_TEST_BASE_DIR', '/tmp/SIMO_test')
HUB_DIR = os.path.join(BASE_DIR, 'hub')
VAR_DIR = os.path.join(BASE_DIR, '_var')
STATIC_ROOT = os.path.join(VAR_DIR, 'static')
MEDIA_ROOT = os.path.join(VAR_DIR, 'media')
LOG_DIR = os.path.join(VAR_DIR, 'logs')


# Keep protected media/static behavior the same as production.
DEBUG = False

DATABASES['default']['TEST'] = {'NAME': 'SIMO_test'}


# Avoid requiring Redis during unit tests.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "simo-test",
        "TIMEOUT": 300,
    },
}


# Use a fast password hasher.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]
