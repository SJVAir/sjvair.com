"""
EPA's Greenhouse Gas Reporting Program via the Envirofacts REST API (public
domain, no key). Facilities per county (server-side county_fips filter),
then per facility its per-gas CO2e rows and its FRS program ids, whose AIR
entry is the district's facility id (Phase 4's icis.parse_pgm_sys_id).
RY2023 is the newest year published; EPA has proposed ending the program.
"""
import time
from collections import Counter

import requests

from django.contrib.gis.geos import Point
from django.db import transaction

from camp.apps.emissions import ghg, icis
from camp.apps.emissions.models import GHGReport
from camp.apps.regions.models import Region

BASE = 'https://data.epa.gov/efservice'
# The eight counties as 5-digit FIPS; icis has the 3-digit tails.
COUNTY_FIPS = tuple(f'06{tail}' for tail in sorted(icis.FIPS_TO_CARB))
GAS_CO2, GAS_CH4, GAS_N2O, GAS_BIOCO2 = 1, 2, 3, 8
PROGRAM = GHGReport.Program.GHGRP


def gwp(year):
    """
    The global warming potentials GHGRP used to turn tons of gas into CO2e
    (40 CFR 98, Table A-1): AR4 through RY2023, AR5 from RY2024.
    """
    if year <= 2023:
        return {GAS_CH4: 25, GAS_N2O: 298}
    return {GAS_CH4: 28, GAS_N2O: 265}


def facilities_url(year, fips):
    return f'{BASE}/pub_dim_facility/state/CA/year/{year}/county_fips/{fips}/JSON'


def emissions_url(facility_id, year):
    return f'{BASE}/pub_facts_sector_ghg_emission/facility_id/{facility_id}/year/{year}/JSON'


def frs_url(frs_id):
    return f'{BASE}/frs_program_facility/registry_id/{frs_id}/JSON'


def fetch_json(url, retries=3):
    """The one network call. Envirofacts throttles; back off and retry."""
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def gas_totals(rows):
    """
    {gas_id: CO2e} summed over sector rows. A reporter with nothing in the
    emissions table for the year (often a supplier, not an emitter) comes
    back as one placeholder row with a null gas_id and emission; those are
    skipped, so its totals are empty and import_county leaves it out.
    """
    totals = Counter()
    for row in rows:
        if row.get('gas_id') is None:
            continue
        totals[int(row['gas_id'])] += float(row['co2e_emission'] or 0)
    return dict(totals)


def figures(totals, year):
    factors = gwp(year)
    co2e = sum(value for gas, value in totals.items() if gas != GAS_BIOCO2)
    return {
        'co2e': co2e,
        'co2e_biogenic': totals.get(GAS_BIOCO2),
        'ch4': totals[GAS_CH4] / factors[GAS_CH4] if GAS_CH4 in totals else None,
        'n2o': totals[GAS_N2O] / factors[GAS_N2O] if GAS_N2O in totals else None,
    }


def frs_air_id(rows):
    for row in rows:
        if row.get('pgm_sys_acrnm') == 'AIR':
            return (row.get('pgm_sys_id') or '').strip()
    return ''


def import_county(year, county, log):
    """
    One county's reporters for `year`, in one transaction: upsert each, delete
    the ones no longer reported. Returns a Counter of outcomes; `failed`
    reporters are logged and skipped (their existing rows are kept).
    """
    fips = county.external_id
    counts = Counter()
    seen = set()
    failed = set()
    rows = fetch_json(facilities_url(year, fips))
    with transaction.atomic():
        for fac in rows:
            external_id = str(fac['facility_id'])
            try:
                totals = gas_totals(fetch_json(emissions_url(external_id, year)))
                frs_rows = fetch_json(frs_url(fac['frs_id'])) if fac.get('frs_id') else []
            except requests.RequestException as err:
                log.error(f'{external_id} {fac.get("facility_name")}: {err}')
                failed.add(external_id)
                continue
            if not totals:
                counts['no_emissions'] += 1
                continue
            point = None
            if fac.get('latitude') is not None and fac.get('longitude') is not None:
                point = Point(float(fac['longitude']), float(fac['latitude']), srid=4326)
            facility, method = ghg.resolve(
                PROGRAM, external_id, name=fac.get('facility_name') or '', frs_air_id=frs_air_id(frs_rows), point=point,
            )
            GHGReport.objects.update_or_create(
                program=PROGRAM, external_id=external_id, year=year,
                defaults=dict(
                    facility=facility, match_method=method,
                    county=facility.county if facility is not None and facility.county_id else county,
                    name=(fac.get('facility_name') or '')[:128], city=(fac.get('city') or '')[:64],
                    zipcode=(fac.get('zip') or '')[:10], naics=(fac.get('naics_code') or '')[:8],
                    sector=(fac.get('facility_types') or '')[:128], subparts=(fac.get('reported_subparts') or '')[:128],
                    point=point, frs_id=(fac.get('frs_id') or '')[:12], basin_wide=False,
                    **figures(totals, year),
                ),
            )
            seen.add(external_id)
            counts[method or 'unmatched'] += 1
        stale = GHGReport.objects.filter(program=PROGRAM, year=year, county=county).exclude(external_id__in=seen | failed)
        counts['deleted'] += stale.count()
        stale.delete()
    counts['failed'] = len(failed)
    return counts
