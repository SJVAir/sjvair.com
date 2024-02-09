"""
Django settings for the Community Air Monitoring Project.

Generated by 'django-admin startproject' using Django 2.2.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.2/ref/settings/
"""

import os
import subprocess

import dj_database_url

from django.utils.translation import gettext_lazy as _

from unipath import Path

# Build paths inside the project like this: BASE_DIR.child(...)
BASE_DIR = Path(__file__).absolute().ancestor(3)
PROJECT_DIR = Path(__file__).absolute().ancestor(2)

COMMIT_HASH = os.environ.get('HEROKU_SLUG_COMMIT')
if COMMIT_HASH is None:
    COMMIT_HASH = subprocess.check_output(
        ['git', 'rev-parse', '--short', 'HEAD']
    ).strip()

DOMAIN = os.environ.get('DOMAIN', '')

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = bool(int(os.environ.get('DJANGO_DEBUG', 1)))

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost').split(',')

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.gis',
    'django.contrib.humanize',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # 'channels',
    # 'channels_redis',
    'corsheaders',
    'admin_honeypot',
    'django_admin_inline_paginator',
    'django_extensions',
    'django_filters',
    'django_huey',
    'form_utils',
    'huey.contrib.djhuey',
    'livereload',
    'localflavor',
    'resticus',
    'storages',
    'widget_tweaks',

    'camp.api',
    'camp.apps.accounts',
    'camp.apps.alerts',
    'camp.apps.archive',
    'camp.apps.calibrations',
    'camp.apps.contact',
    'camp.apps.qaqc',
    'camp.apps.monitors',
    'camp.apps.monitors.airnow',
    'camp.apps.monitors.aqview',
    'camp.apps.monitors.bam',
    'camp.apps.monitors.methane',
    'camp.apps.monitors.purpleair',
    'camp.apps.sensors',
    'camp.utils',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'camp.api.middleware.MonitorAccessMiddleware',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [PROJECT_DIR.child('templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'camp.context_processors.settings_context',
            ],
            'libraries': {
                'sjvair': 'camp.template_tags',
            }
        },
    },
]

ROOT_URLCONF = 'camp.urls'

WSGI_APPLICATION = 'camp.wsgi.application'


# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases

DATABASES = {
    'default': dj_database_url.config(
        engine='django.contrib.gis.db.backends.postgis'
    )
}


# Redis

REDIS_URL = None
for var in ["REDIS_URL", "OPENREDIS_URL"]:
    REDIS_URL = os.environ.get(var)
    if REDIS_URL is not None:
        if REDIS_URL.startswith('rediss'):
            REDIS_URL = f"{REDIS_URL}{'&' if '?' in REDIS_URL else '?'}ssl_cert_reqs=none"
        break

# Auth

AUTHENTICATION_BACKENDS = (
    # 'django.contrib.auth.backends.ModelBackend',
    'camp.apps.accounts.backends.AuthenticationBackend',
)

AUTH_USER_MODEL = 'accounts.User'

LOGIN_URL = 'account:login'

LOGIN_REDIRECT_URL = '/'

LOGOUT_REDIRECT_URL = '/'


# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators

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

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
]


# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

LANGUAGE_CODE = 'en'

LANGUAGES = (
    ('en', _('English')),
    ('tl', _('Filipino')),
    ('hmn', _('Hmong')),
    ('es', _('Spanish')),
)


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.2/howto/static-files/
STATIC_ROOT = BASE_DIR.child('public', 'static')

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    BASE_DIR.child('assets'),
    BASE_DIR.child('dist'),
]

STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

MEDIA_ROOT = BASE_DIR.child('public', 'media')

MEDIA_URL = os.environ.get('MEDIA_URL', '/media/')

# Email setup

DEFAULT_FROM_EMAIL = 'SJVAir <no-reply@sjvair.com>'

SERVER_EMAIL = 'SJVAir Server <root@sjvair.com>'

SJVAIR_INACTIVE_ALERT_EMAILS = [email.strip() for email in
    os.environ.get('SJVAIR_INACTIVE_ALERT_EMAILS', SERVER_EMAIL).split(',')]

SJVAIR_CONTACT_EMAILS = [email.strip() for email in
    os.environ.get('SJVAIR_CONTACT_EMAILS', SERVER_EMAIL).split(',')]

# django-cors-headers

CORS_ORIGIN_ALLOW_ALL = True

CORS_ALLOW_CREDENTIALS = True

# django-phonenumber-field

PHONENUMBER_DB_FORMAT = "INTERNATIONAL"

PHONENUMBER_DEFAULT_REGION = "US"

# django-resticus

RESTICUS = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'STREAMING': [],
    'PAGE_SIZE_QUERY_PARAM': 'page_size',
}


# huey / django-huey

MAX_QUEUE_SIZE = int(os.environ.get('MAX_QUEUE_SIZE', 500))

DJANGO_HUEY = {
    'default': 'primary',
    'queues': {
        'primary': {
            'name': 'primary_tasks',
            'connection': {'url': f'{REDIS_URL}/0'},
            'consumer': {
                'periodic': True,
                'workers': int(os.environ.get('HUEY_WORKERS', 4))
            },
            'huey_class': 'huey.PriorityRedisHuey',
            'immediate': bool(int(os.environ.get('HUEY_IMMEDIATE', DEBUG)))
        },
        'secondary': {
            'name': 'secondary_tasks',
            'connection': {'url': f'{REDIS_URL}/1'},
            'consumer': {
                'periodic': False,
                'workers': int(os.environ.get('HUEY_WORKERS', 4))
            },
            'huey_class': 'huey.PriorityRedisHuey',
            'immediate': bool(int(os.environ.get('HUEY_IMMEDIATE', DEBUG)))
        },
    }
}

HUEY = {
    
}

# Twilio
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")

TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

TWILIO_PHONE_NUMBERS = os.environ.get("TWILIO_PHONE_NUMBERS", "").split(',')

# SMS Alerts
SEND_SMS_ALERTS = bool(int(os.environ.get('SEND_SMS_ALERTS', 1)))

# Number of minutes between sending
PHONE_VERIFICATION_RATE_LIMIT = int(os.environ.get('PHONE_VERIFICATION_RATE_LIMIT', 2))

# Number of minutes until the code expires
PHONE_VERIFICATION_CODE_EXPIRES = int(os.environ.get('PHONE_VERIFICATION_CODE_EXPIRES', 5))

# Number of digits in the phone verification code
PHONE_VERIFICATION_CODE_DIGITS = int(os.environ.get('PHONE_VERIFICATION_CODE_DIGITS', 6))

# Google Maps
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')

# Google Analytics
GOOGLE_ANALYTICS_ID = os.environ.get('GOOGLE_ANALYTICS_ID')

# Air Now API
AIRNOW_API_KEY = os.environ.get('AIRNOW_API_KEY')

# Purple Air
PURPLEAIR_READ_KEY = os.environ.get('PURPLEAIR_READ_KEY')
PURPLEAIR_WRITE_KEY = os.environ.get('PURPLEAIR_WRITE_KEY')
PURPLEAIR_GROUP_ID = os.environ.get('PURPLEAIR_GROUP_ID')

# Sentry
if "SENTRY_DSN" in os.environ:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        integrations=[DjangoIntegration(transaction_style="url")],
        release=COMMIT_HASH,
    )

# Scout APM
SCOUT_MONITOR = bool(os.environ.get('SCOUT_MONITOR') == 'true')
SCOUT_KEY = os.environ.get('SCOUT_KEY')
SCOUT_NAME = os.environ.get('SCOUT_NAME')
SCOUT_ERRORS_ENABLED = not DEBUG

if SCOUT_KEY is not None:
    INSTALLED_APPS.insert(0, 'scout_apm.django')
