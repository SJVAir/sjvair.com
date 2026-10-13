import time
from collections import Counter
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import stats
from camp.apps.emissions.importers import ghgrp
from camp.apps.emissions.models import GHGReport, SourceImport
from camp.apps.regions.models import Region


class Command(BaseCommand):
    help = (
        "Import EPA GHGRP greenhouse-gas totals for the eight counties' reporters from Envirofacts "
        '(about 350 requests). Idempotent; a reporter that vanishes upstream for the year is deleted.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='Reporting year (2023 is the newest published)')
        parser.add_argument('--county', help='One county slug (default: all eight)')

    def error(self, message):
        self.stderr.write(message)

    def handle(self, *args, **options):
        year = options['year']
        counties = Region.objects.filter(type=Region.Type.COUNTY, external_id__in=ghgrp.COUNTY_FIPS).order_by('name')
        if options['county']:
            counties = counties.filter(slug=options['county'])
            if not counties.exists():
                raise CommandError(f'No covered county with slug {options["county"]!r}.')
        start = time.monotonic()
        total = Counter()
        for county in counties:
            counts = ghgrp.import_county(year, county, self)
            total.update(counts)
            reporters = counts['frs'] + counts['crosswalk'] + counts['auto'] + counts['unmatched']
            self.stdout.write(
                f'{county.name}: {reporters} reporters ({counts["frs"]} frs, {counts["auto"]} auto, '
                f'{counts["unmatched"]} unmatched)'
                + (f', {counts["crosswalk"]} crosswalk' if counts['crosswalk'] else '')
                + (f', {counts["deleted"]} deleted' if counts['deleted'] else '')
                + (f', {counts["failed"]} failed' if counts['failed'] else '')
            )
        matched = total['frs'] + total['crosswalk'] + total['auto']
        reporters = matched + total['unmatched']
        SourceImport.objects.create(
            source='ghgrp', version=str(year), data_through=date(year, 12, 31),
            notes={'reporters': reporters, 'matched': matched, 'unmatched': total['unmatched'],
                   'no_emissions': total['no_emissions'], 'deleted': total['deleted'], 'failed': total['failed']},
        )
        stats.clear_caches()
        self.stdout.write(f'\nDone. {reporters} reporters, {matched} matched [{time.monotonic() - start:.1f}s]')
        if total['failed']:
            raise CommandError(f'{total["failed"]} reporters could not be fetched; re-run for their counties.')
