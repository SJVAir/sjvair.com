from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Import school districts and then public schools, in that order:'
        ' a school links to the district whose boundary it stands in, so'
        ' the districts have to be there first.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--path', default=None,
            help='Read a local public schools file instead of downloading it.')
        parser.add_argument('--no-geocode', dest='no_geocode', action='store_true',
            help='Skip (and count) schools that arrive without coordinates.')

    def handle(self, *args, **options):
        call_command('import_school_districts')
        call_command('import_locations',
            source='cde-public',
            path=options['path'],
            no_geocode=options['no_geocode'],
            stdout=self.stdout,
            stderr=self.stderr,
        )
