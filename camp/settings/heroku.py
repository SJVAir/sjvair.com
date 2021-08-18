import django_heroku

from .base import *

# django_heroku.settings(locals())

# GIS paths

GDAL_LIBRARY_PATH = os.environ.get('GDAL_LIBRARY_PATH')

GEOS_LIBRARY_PATH = os.environ.get('GEOS_LIBRARY_PATH')

# https

SECURE_SSL_REDIRECT = True

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Cache

CACHES = {
    "default": {
        "BACKEND": "django_bmemcached.memcached.BMemcached",
        "LOCATION": os.environ.get("MEMCACHEDCLOUD_SERVERS").split(","),
        "OPTIONS": {
            "username": os.environ.get("MEMCACHEDCLOUD_USERNAME"),
            "password": os.environ.get("MEMCACHEDCLOUD_PASSWORD"),
        },
    }
}

# Huey

# HUEY['always_eager'] = False

if DEBUG:
    INSTALLED_APPS.extend([
        'debug_toolbar'
    ])

    MIDDLEWARE.extend([
        'debug_toolbar.middleware.DebugToolbarMiddleware',
    ])

    DEBUG_TOOLBAR_CONFIG = {
        'SHOW_TOOLBAR_CALLBACK': lambda request: True
    }
