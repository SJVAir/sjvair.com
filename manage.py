#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import pprint
import sys
import zoneinfo

# import dotenv

from django.utils import timezone

def main():
    # Run output through the pretty printer.
    sys.displayhook = pprint.pprint

    # # Load our .env
    # dotenv.load_dotenv(dotenv.find_dotenv())

    # Set PST globally, since that's where we operate.
    timezone.activate(zoneinfo.ZoneInfo('America/Los_Angeles'))

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'camp.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
