import os
import django_heroku

from .base import *

# Domain used to generate URLs.
DOMAIN = os.environ.get('DOMAIN')
if DOMAIN is None and 'HEROKU_APP_NAME' in os.environ:
    DOMAIN = f'https://{os.environ["HEROKU_APP_NAME"]}.herokuapp.com'

# Email via MailerToGo

EMAIL_HOST = os.environ.get('MAILERTOGO_SMTP_HOST')
EMAIL_HOST_USER = os.environ.get('MAILERTOGO_SMTP_USER')
EMAIL_HOST_PASSWORD = os.environ.get('MAILERTOGO_SMTP_PASSWORD')
EMAIL_PORT = os.environ.get('MAILERTOGO_SMTP_PORT')
EMAIL_USE_TLS = True
# MAILERTOGO_DOMAIN = os.environ.get('MAILERTOGO_DOMAIN') # ???


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
