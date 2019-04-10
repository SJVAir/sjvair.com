"""
WSGI config for aqm project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""

import os

import dotenv

from django.core.wsgi import get_wsgi_application
from dj_static import Cling

dotenv.load_dotenv(dotenv.find_dotenv())
application = Cling(get_wsgi_application())
