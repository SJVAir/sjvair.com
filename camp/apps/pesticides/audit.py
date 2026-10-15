"""
A quick check of which pesticides imports have run, from what's in the
database: one row per import step of the deploy (PR #275's deploy notes), in
the order they run, each with a status, what was found and, when something
is missing, the command to run. Read-only; audit_pesticides_imports prints it.

The expected PUR years live here, next to the checks: add a year when CDPR
publishes one (and move the first, lookup-loading run to it).
"""
from datetime import timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone

from camp.apps.pesticides.models import (
    Chemical, PesticideNotice, PesticideSectionTotal, PesticideUse, PesticideUseRollup, PesticideUseTotal,
)
from camp.apps.regions.models import Location, Region
from camp.utils.importaudit import MISSING, NEEDED, OK, PARTIAL, STALE, Step

# The years import_pur should cover, the deploy notes' runs. The newest runs
# first and loads CDPR's lookup tables; the rest run with --skip-lookup.
PUR_YEARS = range(2018, 2024)

# The region imports ahead of the pesticides ones, in the deploy's order:
# (command, the region types it leaves).
REGION_IMPORTS = (
    ('import_counties', (Region.Type.COUNTY,)),
    ('import_zipcodes', (Region.Type.ZIPCODE,)),
    ('import_cities', (Region.Type.CITY, Region.Type.CDP)),
    ('import_mtrs', (Region.Type.MTRS,)),
    ('import_ab617_communities', (Region.Type.AB617_COMMUNITY,)),
    ('import_urban_areas', (Region.Type.URBAN_AREA,)),
    ('import_air_districts', (Region.Type.AIR_DISTRICT,)),
    ('import_census_tracts', (Region.Type.TRACT,)),
)

# The places import_population fills in (AB 617 communities get none).
POPULATION_TYPES = (
    Region.Type.COUNTY, Region.Type.CITY, Region.Type.CDP, Region.Type.ZIPCODE, Region.Type.TRACT, Region.Type.SCHOOL_DISTRICT,
)

# fetch_spraydays runs daily (tasks.fetch_pesticide_notices). SprayDays can go
# a few days without a new notice, so this is generous before crying wolf.
NOTICES_STALE_AFTER = timedelta(days=4)


def _fix(command):
    return f'python manage.py {command}'


def regions(command, types):
    count = Region.objects.filter(type__in=types).count()
    found = f'{count:,} ' + ', '.join(str(Region.Type(t).label) for t in types)
    if not count:
        return Step(command, MISSING, found, _fix(command))
    return Step(command, OK, found)


def population():
    """import_population: which kinds of place carry metadata['population']."""
    have, empty = [], []
    for region_type in POPULATION_TYPES:
        regions = Region.objects.filter(type=region_type)
        total = regions.count()
        if not total:
            continue
        filled = regions.filter(metadata__has_key='population').count()
        (have if filled else empty).append(f'{Region.Type(region_type).label} {filled:,}/{total:,}')
    found = ', '.join(have + empty) or 'no places to fill'
    if not have:
        return Step('import_population', MISSING, found, _fix('import_population'), notes=['needs CENSUS_API_KEY'])
    if empty:
        return Step('import_population', PARTIAL, found, _fix('import_population'), notes=['needs CENSUS_API_KEY'])
    return Step('import_population', OK, found)


def schools():
    """import_schools: the school districts, then CDE's public schools (which link to them)."""
    districts = Region.objects.filter(type=Region.Type.SCHOOL_DISTRICT).count()
    public = Location.objects.filter(source='cde-public').count()
    found = f'{districts:,} school districts, {public:,} public schools'
    if not districts or not public:
        return Step('import_schools', MISSING, found, _fix('import_schools'))
    return Step('import_schools', OK, found)


def locations(source):
    command = f'import_locations --source {source}'
    count = Location.objects.filter(source=source).count()
    if not count:
        return Step(command, MISSING, f'no {source} sites', _fix(command))
    return Step(command, OK, f'{count:,} sites')


def _pur_counts():
    """{year: {county slug: records}} over the covered counties, in one pass over the records."""
    counties = list(Region.objects.counties().order_by('name').values_list('pk', 'slug'))
    rows = PesticideUse.objects.values_list('year', 'county').annotate(n=Count('pk')).values_list('year', 'county', 'n')
    by_year = {}
    for year, county, n in rows:
        by_year.setdefault(year, {})[county] = n
    return {year: {slug: by_year.get(year, {}).get(pk, 0) for pk, slug in counties} for year in PUR_YEARS}


def pur(year, counts):
    """One year of PUR records, county by county: OK with every covered county, PARTIAL with some, MISSING with none."""
    first = year == max(PUR_YEARS)
    command = f'import_pur --year {year}' + ('' if first else ' --skip-lookup')
    have = [slug for slug, n in counts.items() if n]
    found = f'{sum(counts.values()):,} records, {len(have)}/{len(counts)} counties'
    if not have:
        return Step(command, MISSING, found, _fix(command))
    if len(have) < len(counts):
        missing = [slug for slug, n in counts.items() if not n]
        return Step(command, PARTIAL, found, _fix(command), notes=[f'no records for: {", ".join(missing)}'])
    return Step(command, OK, found)


def comptox_search():
    matched = Chemical.objects.exclude(dtxsid='').count()
    found = f'{matched:,} of {Chemical.objects.count():,} chemicals matched to CompTox'
    if not matched:
        return Step('import_comptox --phase search', MISSING, found, _fix('import_comptox --phase search'), notes=['needs COMPTOX_API_KEY'])
    return Step('import_comptox --phase search', OK, found)


def comptox_equals(search):
    """The equals phase leaves the same DTXSIDs search does, so it can't be told apart: it follows search."""
    command = 'import_comptox --phase equals --limit 500 --workers 10'
    note = "leaves the same matches as search; can't be checked on its own"
    if not search.done:
        return Step(command, MISSING, 'search has not run', _fix(command), notes=[note])
    return Step(command, OK, 'follows search', notes=[note])


def comptox_names():
    unnamed = Chemical.objects.exclude(dtxsid='').filter(preferred_name='').count()
    if not Chemical.objects.exclude(dtxsid='').exists():
        return Step('import_comptox --phase names', MISSING, 'no CompTox matches to name', _fix('import_comptox --phase names'))
    if unnamed:
        return Step('import_comptox --phase names', NEEDED, f'{unnamed:,} matches without a preferred name', _fix('import_comptox --phase names'))
    return Step('import_comptox --phase names', OK, 'every match has its preferred name')


def comptox_hazard():
    grouped = Chemical.objects.exclude(iarc_group='').count()
    if not grouped:
        return Step('import_comptox --phase hazard', MISSING, 'no IARC groups', _fix('import_comptox --phase hazard'))
    return Step('import_comptox --phase hazard', OK, f'{grouped:,} chemicals with an IARC group')


def _category(command, categories, noun, fix, notes=()):
    count = Chemical.objects.filter(categories__overlap=list(categories)).count()
    found = f'{count:,} {noun}'
    if not count:
        return Step(command, MISSING, found, fix, notes=list(notes))
    return Step(command, OK, found)


def carbtac():
    return _category('import_carbtac --url', [Chemical.Category.TOXIC_AIR_CONTAMINANT],
        'toxic air contaminants', _fix('import_carbtac --url'))


def restricted_materials():
    return _category('import_restricted_materials', [Chemical.Category.CALIFORNIA_RESTRICTED],
        'California restricted materials', _fix('import_restricted_materials'))


def prop65():
    # Only Prop 65 marks reproductive and developmental toxins; CARB's list also marks carcinogens.
    return _category('import_prop65 --path p65chemicalslist.csv',
        [Chemical.Category.REPRODUCTIVE_TOXIN, Chemical.Category.DEVELOPMENTAL_TOXIN],
        'reproductive or developmental toxins', _fix('import_prop65 --path p65chemicalslist.csv'),
        notes=['download the list by hand: https://oehha.ca.gov/proposition-65/proposition-65-list'])


def rollup(pur_years, pending=False):
    """
    rebuild_pesticide_rollup --all: every table it builds has every year the
    records have. `pending` (an import before it isn't done) makes it NEEDED
    regardless: the rebuild comes after them.
    """
    command = 'rebuild_pesticide_rollup --all'
    tables = {
        'rollup': PesticideUseRollup, 'totals': PesticideUseTotal, 'section totals': PesticideSectionTotal,
    }
    behind = []
    for label, model in tables.items():
        years = set(model.objects.values_list('year', flat=True).distinct())
        missing = sorted(pur_years - years)
        if missing:
            behind.append(f'{label} missing {", ".join(map(str, missing))}')
    found = f'{len(pur_years)} record years' + (f'; {"; ".join(behind)}' if behind else ', all in every table')
    if not pur_years:
        return Step(command, MISSING, 'no records to roll up', _fix(command))
    if behind or pending:
        notes = [] if behind else ['after the imports above']
        return Step(command, NEEDED, found, _fix(command), notes=notes)
    return Step(command, OK, found, notes=['rerun after any chemical list import: the narrowings read the lists'])


def notices():
    """fetch_spraydays (daily): notices exist and the newest arrived recently. Past notices only come back from restore_spraydays_notices."""
    stats = PesticideNotice.objects.aggregate(
        total=Count('pk'), newest=Max('created'), past=Count('pk', filter=Q(scheduled_application__lt=timezone.now())),
    )
    found = f'{stats["total"]:,} notices, {stats["past"]:,} past'
    notes = ['after a pesticides reset: restore_spraydays_notices --path notices.csv brings the archive back']
    if not stats['total']:
        return Step('fetch_spraydays', MISSING, found, _fix('fetch_spraydays'), notes=notes)
    found += f'; newest arrived {stats["newest"]:%Y-%m-%d}'
    if timezone.now() - stats['newest'] > NOTICES_STALE_AFTER:
        return Step('fetch_spraydays', STALE, found, _fix('fetch_spraydays'),
            notes=[f'scheduled daily; nothing new in {NOTICES_STALE_AFTER.days} days', *notes])
    return Step('fetch_spraydays', OK, found)


def audit():
    """
    Every import step, in the deploy notes' order: the regions, population,
    schools and child care, PUR by year (newest first), CompTox's phases,
    the chemical lists, the rollup, then SprayDays.
    """
    steps = [regions(command, types) for command, types in REGION_IMPORTS]
    steps += [population(), schools(), locations('cde-private'), locations('cdss-ccl')]
    counts = _pur_counts()
    steps += [pur(year, counts[year]) for year in sorted(PUR_YEARS, reverse=True)]
    search = comptox_search()
    steps += [search, comptox_equals(search), comptox_names(), comptox_hazard()]
    steps += [carbtac(), restricted_materials(), prop65()]
    pending = any(not step.done for step in steps)
    steps += [rollup(set(PesticideUse.objects.values_list('year', flat=True).distinct()), pending=pending), notices()]
    return steps
