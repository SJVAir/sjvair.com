from .base import *

# Fixtures

FIXTURE_DIRS = (os.path.join(BASE_DIR, 'fixtures'),)


# Mail

EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'

EMAIL_FILE_PATH = BASE_DIR.child('outbox')

# Cache

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.memcached.PyLibMCCache',
        'LOCATION': 'localhost:11211',
    }
}


# Huey

#  HUEY['always_eager'] = False


# Django Debug Toolbar

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
