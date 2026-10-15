from django.core.management.base import BaseCommand

from camp.apps.emissions import audit
from camp.utils import importaudit


class Command(BaseCommand):
    help = (
        'Check which emissions imports have run, from what is in the database: every step of the '
        'deploy, its status, what was found and the command to run for anything missing. Read-only.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true', help='Exit non-zero unless every step looks done')

    def handle(self, *args, **options):
        importaudit.report(self, audit.audit(), strict=options['strict'])
