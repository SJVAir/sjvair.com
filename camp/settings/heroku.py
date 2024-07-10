import os
import django_heroku

from .base import *

# Domain used to generate URLs.
DOMAIN = os.environ.get('DOMAIN')
if DOMAIN is None and 'HEROKU_APP_NAME' in os.environ:
    DOMAIN = f'https://{os.environ["HEROKU_APP_NAME"]}.herokuapp.com'

# AWS S3 Storage

GZIP_CONTENT_TYPES = (
    'text/css',
    'text/csv',
    'text/javascript',
    'application/javascript',
    'application/x-javascript',
    'image/svg+xml',
)

AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')

AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
AWS_S3_CUSTOM_DOMAIN = os.environ.get('AWS_S3_CUSTOM_DOMAIN')
if AWS_S3_CUSTOM_DOMAIN is None:
    AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'

AWS_AUTO_CREATE_BUCKET = True
AWS_BUCKET_ACL = 'public-read'
AWS_DEFAULT_ACL = 'public-read'
AWS_IS_GZIPPED = True
AWS_QUERYSTRING_AUTH = False

# We only use S3 for media files. Static files are
# built locally and manually synced to S3 so that
# we can, e.g., post-process and compress images.
DEFAULT_FILE_STORAGE = 'camp.utils.storage.S3UploadStorage'
DEFAULT_FILE_LOCATION = 'files'
MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/{DEFAULT_FILE_LOCATION}/'

STATICFILES_LOCATION = 'static'
STATIC_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/{STATICFILES_LOCATION}/'

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

# Debug

if DEBUG:
    INSTALLED_APPS.extend([
        'debug_toolbar'
    ])

    MIDDLEWARE.extend([
        'debug_toolbar.middleware.DebugToolbarMiddleware',
        'debug_toolbar_force.middleware.ForceDebugToolbarMiddleware',
    ])

    DEBUG_TOOLBAR_CONFIG = {
        'SHOW_TOOLBAR_CALLBACK': lambda request: True
    }
