"""
Django settings for SIMO.io project.
"""
from simo.settings import *

SECRET_KEY = '{{ secret_key }}'

DEBUG = False

BASE_DIR = '{{ base_dir }}'
HUB_DIR = os.path.join(BASE_DIR, 'hub')
VAR_DIR = os.path.join(BASE_DIR, '_var')
STATIC_ROOT = os.path.join(VAR_DIR, 'static')
MEDIA_ROOT = os.path.join(VAR_DIR, 'media')
LOG_DIR = os.path.join(VAR_DIR, 'logs')
