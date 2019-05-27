from .base import *

FIXTURE_DIRS = [BASE_DIR.child('fixtures')]


# Mail

EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'

EMAIL_FILE_PATH = BASE_DIR.child('outbox')
