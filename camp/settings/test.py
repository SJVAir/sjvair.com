from .base import *
import tempfile

FIXTURE_DIRS = [BASE_DIR.child('fixtures')]

MEDIA_ROOT = tempfile.mkdtemp(prefix='sjvair-test-media-')

# Mail

EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'

EMAIL_FILE_PATH = BASE_DIR.child('outbox')

# Cache

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test-cache',
    }
}

# Background workers

DJANGO_HUEY = {
    'default': 'primary',
    'queues': {
        'primary': {
            'name': 'primary_tasks',
            'consumer': {
                'periodic': False,
                'workers': 1
            },
            'huey_class': 'huey.MemoryHuey',
            'immediate': True
        },
        'secondary': {
            'name': 'secondary_tasks',
            'consumer': {
                'periodic': False,
                'workers': 1
            },
            'huey_class': 'huey.MemoryHuey',
            'immediate': True
        },
        'summaries': {
            'name': 'summaries_tasks',
            'consumer': {
                'periodic': False,
                'workers': 1
            },
            'huey_class': 'huey.MemoryHuey',
            'immediate': True
        },
    }
}
