"""
Django settings for SIMO.io project.
"""
import sys
import os

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = '/etc/SIMO'
HUB_DIR = os.path.join(BASE_DIR, 'hub')
LOG_DIR = '/var/log/simo'

HOST = 'hub'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

ALLOWED_HOSTS = ['*']

VAR_DIR = os.path.join(BASE_DIR, '_var')

FILEBROWSER_DIRECTORY = ''
VAR_DIR_URL = '/var/'

FILEBROWSER_EXTENSIONS = {
    'Image': ['.jpg','.jpeg','.gif','.png','.tif','.tiff', '.flr'],
    'Document': ['.pdf','.doc','.rtf','.txt','.xls','.csv'],
    'Video': ['.mov','.wmv','.mpeg','.mpg','.avi','.rm'],
    'Audio': ['.mp3','.mp4','.wav','.aiff','.midi','.m4p'],
    'System': ['.json', '.xml', '.ini', '.sqlite', ]
}


STATIC_ROOT = os.path.join(VAR_DIR, 'static')

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(VAR_DIR, 'media')

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

INSTALLED_APPS = [
    'daphne',
    #'channels',
    'dal',
    'dal_select2',
    'django.forms',

    'django.contrib.auth',
    'django.contrib.sites',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.gis',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'location_field.apps.DefaultConfig',
    'rest_framework',
    'formtools',
    'dynamic_preferences',
    'easy_thumbnails',
    'django_filters',
    'markdownify.apps.MarkdownifyConfig',

    'bootstrap4',
    'taggit',
    'actstream',

    'simo.core',
    'simo.users',
    'simo.notifications',
    'simo.generic',
    'simo.multimedia',
    'simo.fleet',
    'simo.backups',

    'django.contrib.admin',
    'adminsortable2',
]


MIDDLEWARE = [
    'simo.core.middleware.simo_router_middleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simo.users.middleware.IntroduceUser',
    'simo.core.middleware.instance_middleware'
]


FILE_UPLOAD_MAX_MEMORY_SIZE = 20971520 # 20Mb

ROOT_URLCONF = 'urls'
#WSGI_APPLICATION = 'simo.wsgi.application'

CHANNELS_URLCONF = 'simo.asgi'
ASGI_APPLICATION = "asgi.application"


AUTH_USER_MODEL = 'users.User'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'dynamic_preferences.processors.global_preferences',
                'simo.core.context.additional_templates_context',
            ],
        },
    },
]

FORM_RENDERER = 'django.forms.renderers.TemplatesSetting'


DATABASES = {
    'default': {
        'ENGINE': 'simo.core.db_backend',
        'NAME': 'SIMO',
        'ATOMIC_REQUESTS': False,
    }
}

MQTT_HOST = 'localhost'
MQTT_PORT = 1883


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

AUTHENTICATION_BACKENDS = [
    'simo.users.auth_backends.SIMOUserBackend',
    'simo.users.auth_backends.SSOBackend'
]

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

STATIC_URL = '/static/'

STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'simo.core.api_auth.SecretKeyAuth',
        'simo.core.api_auth.IsAuthenticated',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'simo.users.permissions.IsActivePermission',
        'simo.core.permissions.InstancePermission'
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 1000,
    'DATETIME_FORMAT': '%s.%f',
    'DEFAULT_METADATA_CLASS': 'simo.core.api_meta.SIMOAPIMetadata'
}

REDIS_DB = {
    'celery': 0, 'default_cache': 1, 'select2_cache': 2,
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/%d" % REDIS_DB['default_cache'],
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    },
}



CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERYD_HIJACK_ROOT_LOGGER = False
CELERY_BROKER_URL = 'redis://127.0.0.1:6379/%d' % REDIS_DB['celery']


LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/admin/"
LOGOUT_REDIRECT_URL = 'https://simo.io/hubs/my-hubs/'


SITE_ID = 1

LOGGING = {
   'version': 1,
   'disable_existing_loggers': False,
   'formatters': {
       'verbose': {
           'format': '%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
       },
   },
   'handlers': {
       'console': {
           'level': 'INFO',
           'class': 'logging.StreamHandler',
           'stream': sys.stdout,
           'formatter': 'verbose'
       },
   },
   'loggers': {
       '': {
           'handlers': ['console'],
           'level': 'INFO',
           'propagate': True,
       },
   },
}

DYNAMIC_PREFERENCES = {
    'MANAGER_ATTRIBUTE': 'preferences',
    'REGISTRY_MODULE': 'dynamic_settings',
    'ADMIN_ENABLE_CHANGELIST_FORM': False,
    'SECTION_KEY_SEPARATOR': '__',
    'ENABLE_CACHE': False,
    'VALIDATE_NAMES': True,
}

SESSION_COOKIE_AGE = 60 * 60 * 24 * 365 * 10 # 10 years


THUMBNAIL_ALIASES = {
    '': {
        'sm': {'size': (50, 50), 'crop': True},
        'avatar': {'size': (256, 256), 'crop': True},
    },
}

LOCATION_FIELD = {
    'map.provider': 'openstreetmap',
    'map.zoom': 13,
    'search.provider': 'nominatim',
}

TAGGIT_CASE_INSENSITIVE = True



ACTSTREAM_SETTINGS = {
    'MANAGER': 'simo.core.managers.ActionManager',
    'FETCH_RELATIONS': True,
    'USE_PREFETCH': True,
    'USE_JSONFIELD': True,
    'GFK_FETCH_DEPTH': 1,
}