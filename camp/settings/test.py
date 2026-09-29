from .base import *
import tempfile

FIXTURE_DIRS = [BASE_DIR.child('fixtures')]

MEDIA_ROOT = tempfile.mkdtemp(prefix='sjvair-test-media-')

# Database

# The test tables are never ANALYZEd, so the planner wildly overestimates
# row counts on the multi-table-inheritance Monitor joins and JIT-compiles
# nearly every query, costing ~200ms each for sub-millisecond queries.
DATABASES['default'].setdefault('OPTIONS', {})['options'] = '-c jit=off'

# Argon2 is deliberately slow; tests don't need a secure hash. It stays
# listed so the Argon2 hash in fixtures/users.yaml still verifies.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
]

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

# Huey stats — keep the test Postgres untouched; the vendor stats app's
# startup recorder writes its (empty) tables to a throwaway sqlite db instead.
HUEY_STATS = {
    'capture_args': False,
    'database': 'sqlite:///:memory:',
}
