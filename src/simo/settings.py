"""
Django settings for SIMO.io project.
"""
import sys
import os
import datetime

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = '/etc/SIMO'
HUB_DIR = os.path.join(BASE_DIR, 'hub')
LOG_DIR = '/var/log/simo'

HOST = 'hub'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

# True for cloud-hosted (shared, multi-tenant) "virtual hub" deployments.
# Virtual hubs must avoid exposing any instance-local LAN features publicly.
IS_VIRTUAL = False

# Internal SIMO system accounts (not real hub users).
SYSTEM_USERS = [
    'system@simo.io',
    'device@simo.io',
    'ai@simo.io',
    # Used to attribute automation actions while keeping the account hidden
    # from regular user lists.
    'script@simo.io',
]

# ---------------------------------------------------------------------------
# SIMO SSO configuration
# ---------------------------------------------------------------------------
# Cloud default values are provided for backwards compatibility.
# Local hub deployments should override these in their local `settings.py`
# (see `simo/core/management/_hub_template/hub/settings.py`).
SSO_SERVER = os.environ.get('SIMO_SSO_SERVER', 'https://simo.io/sso-server/')
SSO_PUBLIC_KEY = os.environ.get(
    'SIMO_SSO_PUBLIC_KEY',
    'mzfUL0V4aaxvJOS8o4ahrHPVTggk9J4oNb1Hz8RAoc8jKtDMx8iUDkKR3FZsNblc',
)
SSO_PRIVATE_KEY = os.environ.get(
    'SIMO_SSO_PRIVATE_KEY',
    'l1ELiixCre4SreSPQOdeER3LuQBCvJzGUEfjzSbZsXsyJ9qwVUZwMXhMjLG2yKbO',
)

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
    'django_object_actions',

    'simo.core',
    'simo.users',
    'simo.notifications',
    'simo.generic',
    'simo.automation',
    'simo.multimedia',
    'simo.fleet',
    'simo.backups',
    'simo.mcp_server',

    'admin_shortcuts',
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
        'CONN_HEALTH_CHECKS': True,
        'CONN_MAX_AGE': 300,
        'OPTIONS': {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        }
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
    'DEFAULT_THROTTLE_CLASSES': [
        'simo.core.throttling.SimoAdaptiveThrottle',
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


# Adaptive throttling rules (shared for DRF + `@simo_throttle`).
# Tune aggressively for virtual hubs if needed via local settings override.
SIMO_THROTTLE = {
    # Per-user ban duration (per hub) once any scope threshold is exceeded.
    'ban_seconds': 300,

    # Global overall limits (across all scopes) per user/IP.
    'global_rules': [
        {'window_seconds': 10, 'limit_authenticated': 4000, 'limit_anonymous': 80},
        {'window_seconds': 60, 'limit_authenticated': 20000, 'limit_anonymous': 300},
        {'window_seconds': 300, 'limit_authenticated': 60000, 'limit_anonymous': 800},
    ],

    # Default per-scope limits.
    'default_rules': [
        {'window_seconds': 10, 'limit_authenticated': 1200, 'limit_anonymous': 40},
        {'window_seconds': 60, 'limit_authenticated': 4000, 'limit_anonymous': 120},
        {'window_seconds': 300, 'limit_authenticated': 12000, 'limit_anonymous': 400},
    ],

    # Scope-specific overrides (based on app behavior).
    'scopes': {
        # Polling / high-frequency but legit
        'core.states': [
            {'window_seconds': 10, 'limit_authenticated': 2000, 'limit_anonymous': 60},
            {'window_seconds': 60, 'limit_authenticated': 8000, 'limit_anonymous': 200},
        ],
        'fleet.colonels': [
            {'window_seconds': 10, 'limit_authenticated': 40, 'limit_anonymous': 10},
            {'window_seconds': 60, 'limit_authenticated': 240, 'limit_anonymous': 40},
        ],
        'core.discoveries': [
            {'window_seconds': 10, 'limit_authenticated': 80, 'limit_anonymous': 20},
            {'window_seconds': 60, 'limit_authenticated': 400, 'limit_anonymous': 80},
        ],

        # Burst endpoints
        'core.icons': [
            {'window_seconds': 10, 'limit_authenticated': 400, 'limit_anonymous': 40},
            {'window_seconds': 60, 'limit_authenticated': 1200, 'limit_anonymous': 120},
        ],
        'core.components': [
            {'window_seconds': 10, 'limit_authenticated': 1500, 'limit_anonymous': 60},
            {'window_seconds': 60, 'limit_authenticated': 6000, 'limit_anonymous': 200},
        ],

        # Control surfaces
        'core.control': [
            {'window_seconds': 10, 'limit_authenticated': 200, 'limit_anonymous': 20},
            {'window_seconds': 60, 'limit_authenticated': 800, 'limit_anonymous': 60},
        ],
        'mqtt.control': [
            {'window_seconds': 10, 'limit_authenticated': 200, 'limit_anonymous': 20},
            {'window_seconds': 60, 'limit_authenticated': 800, 'limit_anonymous': 60},
        ],
        'mcp.execute': [
            {'window_seconds': 10, 'limit_authenticated': 120, 'limit_anonymous': 10},
            {'window_seconds': 60, 'limit_authenticated': 600, 'limit_anonymous': 60},
        ],

        # Media
        'media.icons': [
            {'window_seconds': 10, 'limit_authenticated': 5000, 'limit_anonymous': 100},
            {'window_seconds': 60, 'limit_authenticated': 20000, 'limit_anonymous': 300},
        ],
        'media.instances': [
            {'window_seconds': 10, 'limit_authenticated': 2000, 'limit_anonymous': 80},
            {'window_seconds': 60, 'limit_authenticated': 8000, 'limit_anonymous': 200},
        ],
        'media.avatars': [
            {'window_seconds': 10, 'limit_authenticated': 800, 'limit_anonymous': 40},
            {'window_seconds': 60, 'limit_authenticated': 3000, 'limit_anonymous': 120},
        ],
    },
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
        },
        "TIMEOUT": 300
    },
}



CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERYD_HIJACK_ROOT_LOGGER = False
CELERY_BROKER_URL = 'redis://127.0.0.1:6379/%d' % REDIS_DB['celery']
CELERY_BEAT_SCHEDULE_FILENAME = os.path.join(VAR_DIR, "celerybeat-schedule")
CELERY_BEAT_SCHEDULER = "simo.core.utils.celery_beat.SafePersistentScheduler"


LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/admin/"
LOGOUT_REDIRECT_URL = 'https://simo.io/hubs/my-instances/'


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


DATETIME_FORMAT = 'Y-m-d H:i:s'


ADMIN_SHORTCUTS = [
    {
        'shortcuts': [
            {
                'title': 'Components',
                'url': '/admin/core/component/',
                'icon': '💡'
            },
            {
                'title': 'Zones',
                'url': '/admin/core/zone/',
                'icon': '📍',
            },
            {
                'title': 'Categories',
                'url': '/admin/core/category/',
                'icon': '📚'
            },
            {
                'title': 'Colonels',
                'url': '/admin/fleet/colonel/',
                'icon': '🕹️',
            },
            {
                'title': 'User Roles',
                'url': '/admin/users/permissionsrole/',
                'icon': '🎖️'
            },
            {
                'title': 'Instance Users',
                'url': '/admin/users/instanceuser/',
                'icon': '👥'
            },
        ]
    },
]
