"""
Rebuild PesticideUseRollup from PesticideUse, one year at a time.

A single INSERT ... SELECT ... GROUP BY inside a transaction, so readers never
see a half-built year and re-running is safe. Called at the end of import_pur
and from the rebuild_pesticide_rollup command.
"""
from django.db import connection, transaction

from camp.apps.pesticides.models import PesticideUse, PesticideUseRollup

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
GROUP BY year, month, county_id, mtrs_id, chemical_id, product_id, commodity_id
"""


def loaded_years():
    return list(PesticideUse.objects.order_by('year').values_list('year', flat=True).distinct())


def rebuild_year(year):
    """Replace the rollup rows for `year`. Returns the number of rows written."""
    with transaction.atomic():
        PesticideUseRollup.objects.filter(year=year).delete()
        with connection.cursor() as cursor:
            cursor.execute(REBUILD_SQL, [year])
            return cursor.rowcount


def rebuild_all():
    return {year: rebuild_year(year) for year in loaded_years()}
