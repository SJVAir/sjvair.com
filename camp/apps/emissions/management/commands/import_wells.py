import json

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import wellstar


class Command(BaseCommand):
    help = (
        "Import CalGEM's active, idle and new oil and gas wells in the covered counties from the WellSTAR REST layer "
        '(about 66,000 wells, 14 pages, a minute). Upserts on the API number and removes wells no longer returned. '
        'Idempotent. --path reads a saved query response (a JSON file with "features") instead of the service.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--path', help='A saved WellSTAR query response (JSON) to import instead of fetching')

    def handle(self, *args, **options):
        features = []
        if options['path']:
            with open(options['path']) as handle:
                features = json.load(handle).get('features') or []
        else:
            try:
                for number, page in enumerate(wellstar.pages(), 1):
                    features.extend(page)
                    self.stdout.write(f'page {number}: {len(page):,} wells ({len(features):,} so far)')
            except (wellstar.WellSTARError, OSError) as exc:
                raise CommandError(f'WellSTAR: {exc}')
            except Exception as exc:  # requests errors, after the retries
                raise CommandError(f'WellSTAR: {exc}')
        if not features:
            raise CommandError('WellSTAR returned no wells; nothing changed.')
        report = wellstar.apply(features)
        for line in report.lines():
            self.stdout.write(line)
