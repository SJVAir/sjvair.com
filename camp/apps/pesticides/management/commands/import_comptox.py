import difflib
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

# Name corroboration. CompTox's name search matches on synonyms, and its
# synonym lists are loose enough that "ACETIC ACID" once came back as
# maleic hydrazide and "ALCOHOLS, C12-C14" as ethanol (IARC group 1). A
# match is kept only when CompTox's preferred name agrees with CDPR's name
# by one of these tests; anything else is dropped as a bad match.
CORROBORATION_FUZZY_RATIO = 0.6
CORROBORATION_SHORT_NAME = 6
_TOKEN_RE = re.compile(r'[a-z]{4,}')


def _name_key(value):
    return ''.join(ch for ch in value.lower() if ch.isalnum())


def _name_tokens(value):
    return set(_TOKEN_RE.findall(value.lower()))


def corroborated(name, preferred_name):
    """
    Why a CompTox preferred name is accepted as naming the same chemical as
    CDPR's `name`, or '' when it isn't: 'same' (same name modulo case and
    punctuation), 'noletters' (CDPR's is a bare code such as "1080"),
    'token' (a word of four or more letters in common), 'fuzzy' (the two
    names' letters mostly line up: "8-QUINOLINOL" / "8-Hydroxyquinoline"),
    'short' (a CDPR common name of six characters or fewer: "2,4-D", "EPTC",
    whose systematic name shares nothing with it).
    """
    if not preferred_name:
        return ''
    if not any(ch.isalpha() for ch in name):
        return 'noletters'
    key, preferred_key = _name_key(name), _name_key(preferred_name)
    if key == preferred_key:
        return 'same'
    if _name_tokens(name) & _name_tokens(preferred_name):
        return 'token'
    if difflib.SequenceMatcher(None, key, preferred_key).ratio() >= CORROBORATION_FUZZY_RATIO:
        return 'fuzzy'
    if len(name) <= CORROBORATION_SHORT_NAME:
        return 'short'
    return ''


def parse_iarc_group(cancer_call):
    if not cancer_call:
        return ''
    m = IARC_GROUP_RE.search(str(cancer_call))
    if not m:
        return ''
    return m.group(1).upper()


class Command(BaseCommand):
    help = 'Enrich Chemical records with CompTox data (DTXSID, CAS number, preferred name, IARC group).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--phase',
            choices=['search', 'equals', 'names', 'hazard', 'audit', 'all'],
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
        parser.add_argument(
            '--reset',
            action='store_true',
            help='With --phase audit: clear the DTXSID, preferred name, CAS number and IARC group of uncorroborated matches',
        )

    def handle(self, *args, **options):
        api_key = settings.COMPTOX_API_KEY
        if not api_key:
            raise CommandError('COMPTOX_API_KEY is not set.')

        self.chem_client = ctxpy.Chemical(x_api_key=api_key)
        self.haz_client = ctxpy.Hazard(x_api_key=api_key)
        self.workers = options['workers']

        phase = options['phase']

        if phase == 'audit':
            self._phase_audit(reset=options['reset'])
            return

        if phase in ('search', 'all'):
            self._phase_search()
            self._phase_cas_lookup()

        if phase in ('equals', 'all'):
            self._phase_equals(limit=options['limit'])

        if phase in ('names', 'all'):
            self._phase_names()

        if phase in ('hazard', 'all'):
            self._phase_hazard(inspect=options['inspect'])

    # --- Phase 1: name search → DTXSID + CAS number ---

    def _phase_search(self):
        self.stdout.write('Phase 1: searching CompTox by chemical name...')
        chemicals = list(Chemical.objects.filter(dtxsid='').values('id', 'name', 'cas_number'))
        self.stdout.write(f'  {len(chemicals):,} chemicals without DTXSID')

        # Whole names only. Searching the part before the comma as well
        # ("2,4-D, BUTOXYETHANOL ESTER" -> "2,4-d") matched salts and esters
        # to their parent, or to whatever shares a synonym with the stem.
        term_to_ids = {}
        name_by_id = {}
        for c in chemicals:
            term_to_ids.setdefault(c['name'].lower(), set()).add(c['id'])
            name_by_id[c['id']] = c['name']

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
                    casrn = result.get('casrn', '')
                    if not result.get('dtxsid'):
                        continue
                    chem_ids = {
                        chem_id for chem_id in term_to_ids.get(search_value, set())
                        if corroborated(name_by_id[chem_id], result.get('preferredName') or '')
                    }
                    if not chem_ids:
                        continue
                    rows = Chemical.objects.filter(pk__in=chem_ids, dtxsid='').update(**self._match_fields(result))
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
                    if not result.get('dtxsid'):
                        continue
                    chem_ids = cas_to_ids.get(search_value, set())
                    if not chem_ids:
                        continue
                    rows = Chemical.objects.filter(pk__in=chem_ids, dtxsid='').update(**self._match_fields(result))
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
                    if not r.get('dtxsid') or not corroborated(chem['name'], r.get('preferredName') or ''):
                        continue
                    fields = self._match_fields(r)
                    if r.get('casrn') and not chem['cas_number']:
                        fields['cas_number'] = r['casrn']
                    return chem['id'], fields
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
                    chem_id, fields = result
                    Chemical.objects.filter(pk=chem_id, dtxsid='').update(**fields)
                    updated += 1
                if completed % 50 == 0:
                    self.stdout.write(f'  {completed:,} / {len(chemicals):,}', ending='\r')

        self.stdout.write(f'\n  Updated {updated:,} chemicals with DTXSID via equals search')

    def _search_with_retry(self, batch):
        return self._with_retry(self.chem_client.search, by='batch', query=batch)

    def _with_retry(self, call, retries=3, backoff=5, **kwargs):
        for attempt in range(retries):
            try:
                return call(**kwargs) or []
            except Exception as e:
                if attempt == retries - 1:
                    self.stderr.write(f'  Batch failed after {retries} attempts: {e}')
                    return []
                time.sleep(backoff * (attempt + 1))

    @staticmethod
    def _match_fields(result):
        """The Chemical fields a CompTox match fills in: the DTXSID, plus the preferred name when given."""
        fields = {'dtxsid': result.get('dtxsid', '')}
        preferred = (result.get('preferredName') or '').strip()
        if preferred:
            fields['preferred_name'] = preferred[:256]
        return fields

    # --- Phase 1d: preferred names for chemicals matched before names were kept ---

    def _phase_names(self):
        self.stdout.write('Phase 1d: preferred names for chemicals with a DTXSID...')
        chemicals = list(
            Chemical.objects.exclude(dtxsid='').filter(preferred_name='').values('id', 'dtxsid')
        )
        self.stdout.write(f'  {len(chemicals):,} chemicals without a preferred name')
        if not chemicals:
            return

        ids_by_dtxsid = {}
        for c in chemicals:
            ids_by_dtxsid.setdefault(c['dtxsid'], set()).add(c['id'])
        dtxsids = list(ids_by_dtxsid.keys())
        batches = [dtxsids[i:i + BATCH_SIZE] for i in range(0, len(dtxsids), BATCH_SIZE)]

        def lookup(batch):
            return self._with_retry(self.chem_client.details, by='batch-dtxsid', query=batch, subset='identifiers')

        updated = 0
        completed = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(lookup, batch): batch for batch in batches}
            for future in as_completed(futures):
                completed += 1
                for row in future.result():
                    preferred = (row.get('preferredName') or '').strip()
                    chem_ids = ids_by_dtxsid.get(row.get('dtxsid', ''), set())
                    if not preferred or not chem_ids:
                        continue
                    updated += Chemical.objects.filter(pk__in=chem_ids, preferred_name='').update(preferred_name=preferred[:256])
                self.stdout.write(f'  {completed:,} / {len(batches):,} batches', ending='\r')

        self.stdout.write(f'\n  Updated {updated:,} chemicals with a preferred name')

    # --- Audit: which existing matches would the corroboration rule keep? ---

    def _phase_audit(self, reset=False):
        self.stdout.write('Audit: corroborating existing DTXSID matches by name...')
        chemicals = list(Chemical.objects.exclude(dtxsid='').values('id', 'name', 'preferred_name', 'dtxsid', 'iarc_group'))
        unnamed = [c for c in chemicals if not c['preferred_name']]
        if unnamed:
            self.stdout.write(f'  {len(unnamed):,} matches have no preferred name yet; run --phase names first to audit them')
        reasons = {}
        rejected = []
        for c in chemicals:
            if not c['preferred_name']:
                continue
            reason = corroborated(c['name'], c['preferred_name'])
            reasons[reason or 'uncorroborated'] = reasons.get(reason or 'uncorroborated', 0) + 1
            if not reason:
                rejected.append(c)
        for reason, count in sorted(reasons.items(), key=lambda item: -item[1]):
            self.stdout.write(f'  {reason:>15}: {count:,}')
        with_iarc = sum(1 for c in rejected if c['iarc_group'])
        self.stdout.write(f'  Uncorroborated: {len(rejected):,} ({with_iarc:,} with an IARC group)')
        for c in rejected[:20]:
            self.stdout.write(f'    {c["name"]!r} -> {c["preferred_name"]!r} {c["dtxsid"]} {c["iarc_group"]}')
        if len(rejected) > 20:
            self.stdout.write(f'    ... and {len(rejected) - 20:,} more')
        if not reset:
            self.stdout.write('  Re-run with --reset to clear them (then run search, equals, names and hazard again).')
            return
        # The CAS number goes too: for these it most likely came from the
        # bad match. import_pur restores CDPR's own CAS numbers.
        cleared = Chemical.objects.filter(pk__in=[c['id'] for c in rejected]).update(
            dtxsid='', preferred_name='', cas_number='', iarc_group='',
        )
        self.stdout.write(f'  Cleared {cleared:,} matches')

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
