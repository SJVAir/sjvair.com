import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote

import ctxpy
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from camp.apps.pesticides.models import Chemical

BATCH_SIZE = 200

IARC_GROUP_RE = re.compile(r'group\s+(2[ab]|[13])', re.IGNORECASE)


def parse_iarc_group(cancer_call):
    if not cancer_call:
        return ''
    m = IARC_GROUP_RE.search(str(cancer_call))
    if not m:
        return ''
    return m.group(1).upper()


class Command(BaseCommand):
    help = 'Enrich Chemical records with CompTox data (DTXSID, CAS number, IARC group).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--phase',
            choices=['search', 'equals', 'hazard', 'all'],
            default='all',
            help='Which phase to run (default: all)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=500,
            help='Max chemicals for equals phase, ranked by PUR record count (default: 500)',
        )
        parser.add_argument(
            '--workers',
            type=int,
            default=10,
            help='Thread pool size for parallel phases (default: 10)',
        )
        parser.add_argument(
            '--inspect',
            action='store_true',
            help='Print raw hazard response for the first chemical and exit',
        )

    def handle(self, *args, **options):
        api_key = settings.COMPTOX_API_KEY
        if not api_key:
            raise CommandError('COMPTOX_API_KEY is not set.')

        self.chem_client = ctxpy.Chemical(x_api_key=api_key)
        self.haz_client = ctxpy.Hazard(x_api_key=api_key)
        self.workers = options['workers']

        phase = options['phase']

        if phase in ('search', 'all'):
            self._phase_search()
            self._phase_cas_lookup()

        if phase in ('equals', 'all'):
            self._phase_equals(limit=options['limit'])

        if phase in ('hazard', 'all'):
            self._phase_hazard(inspect=options['inspect'])

    # --- Phase 1: name search → DTXSID + CAS number ---

    def _phase_search(self):
        self.stdout.write('Phase 1: searching CompTox by chemical name...')
        chemicals = list(Chemical.objects.filter(dtxsid='').values('id', 'name', 'cas_number'))
        self.stdout.write(f'  {len(chemicals):,} chemicals without DTXSID')

        term_to_ids = {}
        for c in chemicals:
            full = c['name'].lower()
            term_to_ids.setdefault(full, set()).add(c['id'])
            if ',' in c['name']:
                base = c['name'].split(',')[0].strip().lower()
                if base != full:
                    term_to_ids.setdefault(base, set()).add(c['id'])

        all_terms = list(term_to_ids.keys())
        batches = [all_terms[i:i + BATCH_SIZE] for i in range(0, len(all_terms), BATCH_SIZE)]
        updated = 0
        completed = 0

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self._search_with_retry, batch): batch for batch in batches}
            for future in as_completed(futures):
                completed += 1
                for result in future.result():
                    search_value = unquote(result.get('searchValue') or '').lower()
                    dtxsid = result.get('dtxsid', '')
                    casrn = result.get('casrn', '')
                    if not dtxsid:
                        continue
                    chem_ids = term_to_ids.get(search_value, set())
                    if not chem_ids:
                        continue
                    rows = Chemical.objects.filter(pk__in=chem_ids, dtxsid='').update(dtxsid=dtxsid)
                    if casrn:
                        Chemical.objects.filter(pk__in=chem_ids, cas_number='').update(cas_number=casrn)
                    updated += rows
                self.stdout.write(f'  {completed:,} / {len(batches):,} batches', ending='\r')

        self.stdout.write(f'\n  Updated {updated:,} chemicals with DTXSID')

    def _phase_cas_lookup(self):
        self.stdout.write('Phase 1b: CAS-based DTXSID lookup...')
        chemicals = list(
            Chemical.objects.exclude(cas_number='').filter(dtxsid='').values('id', 'cas_number')
        )
        self.stdout.write(f'  {len(chemicals):,} chemicals with CAS but no DTXSID')
        if not chemicals:
            return

        cas_to_ids = {}
        for c in chemicals:
            cas_to_ids.setdefault(c['cas_number'], set()).add(c['id'])

        all_cas = list(cas_to_ids.keys())
        batches = [all_cas[i:i + BATCH_SIZE] for i in range(0, len(all_cas), BATCH_SIZE)]
        updated = 0
        completed = 0

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self._search_with_retry, batch): batch for batch in batches}
            for future in as_completed(futures):
                completed += 1
                for result in future.result():
                    search_value = unquote(result.get('searchValue') or '').upper()
                    dtxsid = result.get('dtxsid', '')
                    if not dtxsid:
                        continue
                    chem_ids = cas_to_ids.get(search_value, set())
                    if not chem_ids:
                        continue
                    rows = Chemical.objects.filter(pk__in=chem_ids, dtxsid='').update(dtxsid=dtxsid)
                    updated += rows
                self.stdout.write(f'  {completed:,} / {len(batches):,} batches', ending='\r')

        self.stdout.write(f'\n  Updated {updated:,} chemicals with DTXSID via CAS lookup')

    def _phase_equals(self, limit):
        self.stdout.write(f'Phase 1c: equals search for top {limit:,} unmatched chemicals...')
        chemicals = list(
            Chemical.objects
            .filter(dtxsid='')
            .annotate(record_count=Count('pesticide_uses'))
            .order_by('-record_count')
            .values('id', 'name', 'cas_number')[:limit]
        )
        self.stdout.write(f'  {len(chemicals):,} chemicals to search')

        def lookup(chem):
            try:
                results = self.chem_client.search(by='equals', query=chem['name']) or []
                for r in results:
                    dtxsid = r.get('dtxsid', '')
                    casrn = r.get('casrn', '')
                    if not dtxsid:
                        continue
                    return chem['id'], dtxsid, casrn if not chem['cas_number'] else ''
            except Exception:
                pass
            return None

        updated = 0
        completed = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(lookup, c): c for c in chemicals}
            for future in as_completed(futures):
                completed += 1
                result = future.result()
                if result:
                    chem_id, dtxsid, casrn = result
                    fields = {'dtxsid': dtxsid}
                    if casrn:
                        fields['cas_number'] = casrn
                    Chemical.objects.filter(pk=chem_id, dtxsid='').update(**fields)
                    updated += 1
                if completed % 50 == 0:
                    self.stdout.write(f'  {completed:,} / {len(chemicals):,}', ending='\r')

        self.stdout.write(f'\n  Updated {updated:,} chemicals with DTXSID via equals search')

    def _search_with_retry(self, batch, retries=3, backoff=5):
        for attempt in range(retries):
            try:
                return self.chem_client.search(by='batch', query=batch) or []
            except Exception as e:
                if attempt == retries - 1:
                    self.stderr.write(f'  Batch failed after {retries} attempts: {e}')
                    return []
                time.sleep(backoff * (attempt + 1))

    # --- Phase 2: hazard lookup → IARC group ---

    def _phase_hazard(self, inspect=False):
        self.stdout.write('Phase 2: fetching hazard data for IARC group...')
        chemicals = list(
            Chemical.objects.exclude(dtxsid='').filter(iarc_group='').values('id', 'dtxsid')
        )
        self.stdout.write(f'  {len(chemicals):,} chemicals to check')

        if inspect and chemicals:
            dtxsid = chemicals[0]['dtxsid']
            self.stdout.write(f'\n--- Inspect: raw cancer hazard for {dtxsid} ---')
            df = self.haz_client.search_toxvaldb(by='cancer', dtxsid=dtxsid)
            self.stdout.write(str(df))
            self.stdout.write('---')
            return

        def lookup(chem):
            return chem['id'], self._get_iarc_group(chem['dtxsid'])

        updated = 0
        completed = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(lookup, c): c for c in chemicals}
            for future in as_completed(futures):
                completed += 1
                chem_id, iarc_group = future.result()
                if iarc_group:
                    Chemical.objects.filter(pk=chem_id).update(iarc_group=iarc_group)
                    updated += 1
                if completed % 50 == 0:
                    self.stdout.write(f'  {completed:,} / {len(chemicals):,}', ending='\r')

        self.stdout.write(f'\n  Updated {updated:,} chemicals with IARC group')

    def _get_iarc_group(self, dtxsid):
        try:
            df = self.haz_client.search_toxvaldb(by='cancer', dtxsid=dtxsid)
            if df is None or df.empty:
                return ''
            iarc_rows = df[df['source'].str.contains('IARC', case=False, na=False)]
            if iarc_rows.empty:
                return ''
            for val in iarc_rows['cancerCall'].dropna():
                group = parse_iarc_group(val)
                if group:
                    return group
            return ''
        except Exception:
            return ''
