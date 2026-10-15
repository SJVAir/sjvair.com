"""
A quick check of which emissions imports have run, from what's in the
database: one row per import step of the deploy (PR #282's deploy notes), in
the order they run, each with a status, what was found and, when something
is missing, the command to run. Read-only; audit_emissions_imports prints it.

The expected years live here, next to the checks: add a year when CARB, EPA
or the explorer adds one.
"""
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from camp.apps.emissions import cepam, locations
from camp.apps.emissions.models import (
    AirComplianceFacility, CountyInventory, CountyNEI, Dairy, DairyHerd, DigesterGrant, EmissionsRecord, Facility,
    GHGReport, MethanePlume, MethaneSource, SourceImport, ToxicEmission, ToxicPollutant, Well,
)
from camp.apps.regions.models import Region
from camp.utils.importaudit import MISSING, NEEDED, OK, PARTIAL, STALE, Step

# The years each yearly import should cover (the deploy notes' runs).
CEIDARS_YEARS = range(2018, 2025)
CEPAM_YEARS = range(2018, 2025)
GHGRP_YEARS = range(2018, 2024)  # GHGRP's newest published year is 2023.
MRR_YEARS = (2024,)  # The workbook importers/mrr.py downloads.
NEI_YEARS = (2023,)  # The release importers/nei.py downloads.

# The scheduled imports (tasks.py) and how old their newest run can be before
# it's flagged: twice the schedule, so one missed run doesn't cry wolf.
STALE_AFTER = {
    'icis-air': timedelta(days=14),       # weekly, Mondays
    'wellstar': timedelta(days=14),       # weekly, Sundays
    'carbon-mapper': timedelta(days=62),  # monthly, the 4th
}

def _stamp(source, version=None):
    """The newest SourceImport for `source` (and `version`, a yearly one), or None."""
    stamps = SourceImport.objects.filter(source=source)
    if version is not None:
        stamps = stamps.filter(version=str(version))
    return stamps.order_by('-imported_at', '-pk').first()


def _stamped(stamp):
    return f'last run {stamp.imported_at:%Y-%m-%d}' if stamp else 'no run recorded'


def _by_county(queryset, county_field):
    """{county slug: rows} over the covered counties, for a yearly import that runs county by county."""
    counts = dict(queryset.values_list(county_field).annotate(n=Count('pk')).values_list(county_field, 'n'))
    return {county.slug: counts.get(county.pk, 0) for county in Region.objects.counties().order_by('name')}


def _county_step(command, counts, noun, fix, extra=''):
    """A county-by-county import's row: OK with every covered county, PARTIAL with some (naming the missing), MISSING with none."""
    have = [slug for slug, n in counts.items() if n]
    total = sum(counts.values())
    found = f'{total:,} {noun}, {len(have)}/{len(counts)} counties' + (f'; {extra}' if extra else '')
    if not have:
        return Step(command, MISSING, found, fix)
    if len(have) < len(counts):
        missing = [slug for slug, n in counts.items() if not n]
        return Step(command, PARTIAL, found, fix, notes=[f'no rows for: {", ".join(missing)}'])
    return Step(command, OK, found)


def health_values():
    count = ToxicPollutant.objects.exclude(health_values_date=None).count()
    stamp = _stamp('contable')
    found = f'{count:,} pollutants with health values; {_stamped(stamp)}'
    if not count:
        return Step('import_health_values --url', MISSING, found, 'python manage.py import_health_values --url')
    return Step('import_health_values --url', OK, found)


def ceidars(year):
    counts = _by_county(EmissionsRecord.objects.filter(year=year), 'facility__county')
    return _county_step(f'import_ceidars --year {year}', counts, 'facility records', f'python manage.py import_ceidars --year {year}')


def ceidars_toxics(year):
    """import_ceidars ends with the year's toxics crawl (import_toxics); a crawl that failed leaves the year's facilities without toxics."""
    counts = _by_county(ToxicEmission.objects.filter(year=year), 'facility__county')
    stamp = _stamp('ceidars-toxics', year)
    step = _county_step(
        f'  toxics crawl {year}', counts, 'toxic emissions', f'python manage.py import_toxics --year {year}', extra=_stamped(stamp),
    )
    return step


def facility_points():
    """clean_facility_points has run when there's nothing left for it to clear (a new CEIDARS year can bring more)."""
    to_clear = len(points_to_clear())
    if to_clear:
        return Step('clean_facility_points', NEEDED, f'{to_clear:,} facility points it would clear', 'python manage.py clean_facility_points')
    return Step('clean_facility_points', OK, 'no points left to clear')


def points_to_clear():
    """The facilities clean_facility_points clears (and the audit counts): a point outside the facility's county, or geocoded from a non-address."""
    cleared = []
    for county in Region.objects.counties().select_related('boundary').order_by('name'):
        area = locations.county_area(county)
        facilities = Facility.objects.filter(county=county, point__isnull=False)
        outside = facilities.exclude(point__within=area) if area is not None else facilities.none()
        cleared.extend(outside)
        cleared.extend(
            facility for facility in facilities.exclude(pk__in=outside.values('pk'))
            if not locations.is_geocodable(facility.address)
        )
    return cleared


def _scheduled(command, source, found, fix):
    """A scheduled import's row: MISSING with nothing, STALE when its newest run is older than STALE_AFTER allows."""
    stamp = _stamp(source)
    found = f'{found}; {_stamped(stamp)}'
    if stamp is None:
        return Step(command, MISSING, found, fix)
    if timezone.now() - stamp.imported_at > STALE_AFTER[source]:
        return Step(command, STALE, found, fix, notes=[f'scheduled; older than {STALE_AFTER[source].days} days'])
    return Step(command, OK, found)


def icis_air():
    count = AirComplianceFacility.objects.count()
    if not count:
        return Step('import_icis_air', MISSING, 'no EPA compliance records', 'python manage.py import_icis_air')
    return _scheduled('import_icis_air', 'icis-air', f'{count:,} EPA-tracked facilities', 'python manage.py import_icis_air')


def ghg(program, year):
    command = f'import_{program} --year {year}' + (' --url' if program == GHGReport.Program.MRR else '')
    reports = GHGReport.objects.filter(program=program, year=year)
    count = reports.count()
    stamp = _stamp(program, year)
    found = f'{count:,} reports, {reports.exclude(facility=None).count():,} matched to a facility; {_stamped(stamp)}'
    if not count:
        return Step(command, MISSING, found, f'python manage.py {command}')
    notes = []
    if stamp is not None and (stamp.notes or {}).get('failed'):
        # import_ghgrp names the counties to re-run when EPA errors.
        notes.append(f"{stamp.notes['failed']} reporters failed on the last run: re-run the counties it named")
    return Step(command, PARTIAL if notes else OK, found, f'python manage.py {command}' if notes else '', notes=notes)


def cepam_year(year):
    counts = _by_county(CountyInventory.objects.filter(year=year, inventory=cepam.INVENTORY), 'county')
    return _county_step(
        f'import_cepam --year {year}', counts, 'inventory rows', f'python manage.py import_cepam --year {year}',
    )


def cadd():
    dairies = Dairy.objects.count()
    years = sorted(DairyHerd.objects.values_list('year', flat=True).distinct())
    if not dairies or not years:
        return Step('import_cadd --url', MISSING, 'no dairies', 'python manage.py import_cadd --url')
    return Step('import_cadd --url', OK, f'{dairies:,} dairies, herds {years[0]}–{years[-1]}')


def ddrdp():
    grants = DigesterGrant.objects.count()
    stamp = _stamp('ddrdp')
    found = f'{grants:,} digester grants, {DigesterGrant.objects.exclude(dairy=None).count():,} matched to a dairy; {_stamped(stamp)}'
    if not grants:
        return Step('import_ddrdp', MISSING, found, 'python manage.py import_ddrdp')
    if not Dairy.objects.exists():
        return Step('import_ddrdp', PARTIAL, found, 'python manage.py import_ddrdp', notes=['run after import_cadd: it matches grants to dairies'])
    return Step('import_ddrdp', OK, found)


def well_list():
    count = Well.objects.count()
    if not count:
        return Step('import_wells', MISSING, 'no wells', 'python manage.py import_wells')
    return _scheduled('import_wells', 'wellstar', f'{count:,} wells', 'python manage.py import_wells')


def carbon_mapper():
    sources = MethaneSource.objects.count()
    if not sources:
        return Step('import_carbon_mapper', MISSING, 'no methane sources', 'python manage.py import_carbon_mapper')
    plumes = MethanePlume.objects.count()
    step = _scheduled('import_carbon_mapper', 'carbon-mapper', f'{sources:,} sources, {plumes:,} plumes', 'python manage.py import_carbon_mapper')
    if not plumes and step.status == OK:
        # --no-plumes, or the plume fetch failed: the map has no plume images.
        return Step(step.command, PARTIAL, step.found, 'python manage.py import_carbon_mapper', notes=['no plumes'])
    return step


def nei(year):
    counts = _by_county(CountyNEI.objects.filter(year=year), 'county')
    return _county_step(
        f'import_nei --year {year}', counts, 'county rows', f'python manage.py import_nei --year {year}', extra=_stamped(_stamp('nei', year)),
    )


def audit():
    """
    Every import step, in the deploy notes' order: dyno A (health values,
    CEIDARS by year with its toxics crawl, the point cleanup, ICIS-Air,
    GHGRP, MRR), then dyno B (CEPAM, CADD, DDRDP, wells, Carbon Mapper, NEI).
    """
    steps = [health_values()]
    for year in sorted(CEIDARS_YEARS, reverse=True):
        steps += [ceidars(year), ceidars_toxics(year)]
    steps += [facility_points(), icis_air()]
    steps += [ghg(GHGReport.Program.GHGRP, year) for year in GHGRP_YEARS]
    steps += [ghg(GHGReport.Program.MRR, year) for year in MRR_YEARS]
    steps += [cepam_year(year) for year in CEPAM_YEARS]
    steps += [cadd(), ddrdp(), well_list(), carbon_mapper()]
    steps += [nei(year) for year in NEI_YEARS]
    return steps
