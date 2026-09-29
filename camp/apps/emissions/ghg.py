"""
Greenhouse-gas reports (GHGReport): the read side for the facility card and
the county table. Matching a program's row to a facility is importers.ghg.
"""
from django.core.cache import cache
from django.db.models import Max, Q

from camp.apps.emissions import stats
from camp.apps.emissions.models import GHGReport, SourceImport


PROGRAMS = (GHGReport.Program.MRR, GHGReport.Program.GHGRP)


def latest_years():
    """{program: its newest year with rows}; empty before any import."""
    years = {}
    for program in PROGRAMS:
        year = GHGReport.objects.filter(program=program).aggregate(year=Max('year'))['year']
        if year is not None:
            years[str(program)] = year
    return years


def facility_card(facility):
    """The facility's newest report per program (MRR first, the newer year), or None for no card."""
    rows = []
    for program in PROGRAMS:
        report = facility.ghg_reports.filter(program=program, basin_wide=False).order_by('-year', '-pk').first()
        if report is not None:
            rows.append(report)
    return rows or None


def county_table(county, limit=10):
    """
    The county's largest reporters across both programs' newest years: one
    row per matched facility (both figures), one per unmatched report. None
    before any import (not cached, so the first import shows up at once).
    """
    years = latest_years()
    if not years:
        return None

    def compute():
        wanted = Q()
        for program, year in years.items():
            wanted |= Q(program=program, year=year)
        groups = {}
        # MRR first (see below): a matched facility's `sector` should be
        # MRR's more descriptive one ("Other Combustion Source"), not
        # GHGRP's blunt "Direct Emitter"; `-program` sorts 'mrr' before
        # 'ghgrp', and the `or` below keeps whichever came first.
        reports = GHGReport.objects.filter(county=county).filter(wanted).select_related('facility').order_by('-program', '-co2e')
        for report in reports:
            key = ('facility', report.facility_id) if report.facility_id else (report.program, report.external_id)
            row = groups.setdefault(key, {
                'name': report.facility.name if report.facility_id else report.name,
                'facility': report.facility, 'sector': '', 'basin_wide': False, 'mrr': None, 'ghgrp': None, 'ch4': None,
            })
            row[str(report.program)] = report.co2e
            row['sector'] = row['sector'] or report.sector
            row['basin_wide'] = row['basin_wide'] or report.basin_wide
            if report.ch4 is not None:
                row['ch4'] = max(row['ch4'] or 0.0, report.ch4)
        rows = sorted(groups.values(), key=lambda row: -max(row['mrr'] or 0.0, row['ghgrp'] or 0.0))
        return {'years': years, 'rows': rows[:limit]}

    return cache.get_or_set(f'{stats.prefix()}:ghg-county:{county.pk}:{limit}', compute, stats.CACHE_TIMEOUT)


def stamps():
    return {str(program): SourceImport.latest(str(program)) for program in (GHGReport.Program.GHGRP, GHGReport.Program.MRR)}
