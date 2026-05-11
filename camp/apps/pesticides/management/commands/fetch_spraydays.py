from django.core.management.base import BaseCommand

from camp.apps.pesticides.spraydays import SJV_COUNTIES, fetch_applications


class Command(BaseCommand):
    help = 'Fetch active SprayDays NOI applications from CDPR.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--county',
            choices=list(SJV_COUNTIES.keys()),
            metavar='CODE',
            help=f'Limit to a single county code ({", ".join(SJV_COUNTIES)})',
        )

    def handle(self, *args, **options):
        fetch_applications(
            county_filter=options.get('county'),
            stdout=self.stdout,
        )
