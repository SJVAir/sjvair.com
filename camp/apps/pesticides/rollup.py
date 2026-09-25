"""
Rebuild PesticideUseRollup from PesticideUse, one year at a time.

A single INSERT ... SELECT ... GROUP BY inside a transaction, so readers never
see a half-built year and re-running is safe. Called at the end of import_pur
and from the rebuild_pesticide_rollup command.
"""
from contextlib import nullcontext

from django.db import connection, transaction

from camp.apps.pesticides.models import (
    PesticideSectionTotal, PesticideUse, PesticideUseRollup, PesticideUseTotal,
)

REBUILD_SQL = """
INSERT INTO pesticides_pesticideuserollup
    (year, month, county_id, mtrs_id, chemical_id, product_id, commodity_id,
     lbs_chemical, lbs_product, acres_treated, applications)
SELECT
    year,
    COALESCE(EXTRACT(MONTH FROM application_date)::int, 0) AS month,
    county_id,
    mtrs_id,
    chemical_id,
    product_id,
    commodity_id,
    COALESCE(SUM(lbs_chemical), 0),
    COALESCE(SUM(lbs_product), 0),
    COALESCE(SUM(acres_treated), 0),
    COUNT(*)
FROM pesticides_pesticideuse
WHERE year = %s
-- `month` here resolves to the SELECT alias, not a source column --
-- pesticides_pesticideuse has no `month` column of its own. If one is ever
-- added, this GROUP BY silently starts grouping by the real column instead
-- of the derived one; switch to positional `GROUP BY 1, 2, ...` to keep
-- grouping on the alias.
GROUP BY year, month, county_id, mtrs_id, chemical_id, product_id, commodity_id
"""


# One INSERT per entity dimension, rolling the per-section rollup up to
# per-(year, county, entity) totals. The explorer list pages read these
# instead of summing ~1,500 rollup rows per entity on every request.
TOTALS_SQL = """
INSERT INTO pesticides_pesticideusetotal
    (year, county_id, chemical_id, product_id, commodity_id,
     lbs_chemical, lbs_product, acres_treated, applications)
SELECT
    year,
    county_id,
    {columns},
    COALESCE(SUM(lbs_chemical), 0),
    COALESCE(SUM(lbs_product), 0),
    COALESCE(SUM(acres_treated), 0),
    COALESCE(SUM(applications), 0)
FROM pesticides_pesticideuserollup
WHERE year = %s AND {field} IS NOT NULL
GROUP BY year, county_id, {field}
"""

TOTALS_FIELDS = ['chemical_id', 'product_id', 'commodity_id']


def totals_sql(field):
    columns = ', '.join(field if name == field else 'NULL' for name in TOTALS_FIELDS)
    return TOTALS_SQL.format(columns=columns, field=field)


# The rollup summed to one row per (year, section), for the map. A block of
# the valley-wide map otherwise aggregates ~57,000 rollup rows to reach ~840
# section totals, and twice that when two years are compared.
SECTION_TOTALS_SQL = """
INSERT INTO pesticides_pesticidesectiontotal
    (year, mtrs_id, lbs_chemical, lbs_product, acres_treated, applications)
SELECT
    year,
    mtrs_id,
    COALESCE(SUM(lbs_chemical), 0),
    COALESCE(SUM(lbs_product), 0),
    COALESCE(SUM(acres_treated), 0),
    COALESCE(SUM(applications), 0)
FROM pesticides_pesticideuserollup
WHERE year = %s AND mtrs_id IS NOT NULL
GROUP BY year, mtrs_id
"""


def loaded_years():
    return list(PesticideUse.objects.order_by('year').values_list('year', flat=True).distinct())


def rollup_years():
    """Years present in the rollup -- what --totals-only rebuilds from."""
    return list(PesticideUseRollup.objects.order_by('year').values_list('year', flat=True).distinct())


def rebuild_totals_year(year, atomic=True):
    """
    Replace the per-county entity totals for `year` from the rollup.
    Returns the number of rows written. Pass `atomic=False` when the caller
    already holds the transaction (rebuild_year does).
    """
    context = transaction.atomic() if atomic else nullcontext()
    with context:
        PesticideUseTotal.objects.filter(year=year).delete()
        written = 0
        with connection.cursor() as cursor:
            for field in TOTALS_FIELDS:
                cursor.execute(totals_sql(field), [year])
                written += cursor.rowcount
        return written


def rebuild_section_totals_year(year, atomic=True):
    """
    Replace the per-section totals for `year` from the rollup. Returns the
    number of rows written. Pass `atomic=False` when the caller already holds
    the transaction (rebuild_year does).
    """
    context = transaction.atomic() if atomic else nullcontext()
    with context:
        PesticideSectionTotal.objects.filter(year=year).delete()
        with connection.cursor() as cursor:
            cursor.execute(SECTION_TOTALS_SQL, [year])
            return cursor.rowcount


def rebuild_year(year):
    """Replace the rollup rows (and their totals) for `year`. Returns the number of rollup rows written."""
    with transaction.atomic():
        PesticideUseRollup.objects.filter(year=year).delete()
        with connection.cursor() as cursor:
            cursor.execute(REBUILD_SQL, [year])
            written = cursor.rowcount
        rebuild_totals_year(year, atomic=False)
        rebuild_section_totals_year(year, atomic=False)
        return written


def rebuild_all():
    return {year: rebuild_year(year) for year in loaded_years()}


def rebuild_totals_all():
    return {
        year: rebuild_totals_year(year) + rebuild_section_totals_year(year)
        for year in rollup_years()
    }
