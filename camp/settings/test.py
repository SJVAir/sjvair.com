from .base import *

FIXTURE_DIRS = [BASE_DIR.child('fixtures')]

# Mail

EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'

EMAIL_FILE_PATH = BASE_DIR.child('outbox')


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
    }
}
