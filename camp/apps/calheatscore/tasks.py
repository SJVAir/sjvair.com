from datetime import datetime, timedelta

from django_huey import db_periodic_task, get_queue
from huey import crontab

from camp.apps.regions.models import Region

from .client import calheatscore_client
from .models import CalHeatScore

DAY_FIELDS = [f'CHS_Day_{day}' for day in range(7)]


def get_sjv_zip_regions():
    sjv_geometry = Region.objects.counties().combined_geometry()
    if sjv_geometry is None:
        return Region.objects.none()

    return Region.objects.filter(type=Region.Type.ZIPCODE).intersects(sjv_geometry)


# CalHeatScore refreshes at 5am and 8am Pacific daily. This runs once at
# 16:00 UTC (9am PDT / 8am PST) — close enough across the DST boundary that
# the source has always refreshed by the time this runs.
@db_periodic_task(crontab(minute='0', hour='16'), priority=50)
def import_calheatscore():
    with get_queue('primary').lock_task('import-calheatscore'):
        regions_by_zip = {region.external_id: region for region in get_sjv_zip_regions()}
        if not regions_by_zip:
            return

        rows = calheatscore_client.query(list(regions_by_zip.keys()))
        for row in rows:
            region = regions_by_zip.get(row.get('ZIP_CODE'))
            if region is None:
                continue

            try:
                base_date = datetime.strptime(row['DATE'], '%Y-%m-%d').date()
            except (KeyError, ValueError):
                # Malformed row from the upstream feed — skip just this ZIP,
                # not the whole day's import for every other ZIP.
                continue

            for lead, field in enumerate(DAY_FIELDS):
                value = row.get(field)
                if value in (None, ''):
                    continue

                try:
                    score = int(value)
                except ValueError:
                    continue

                if score not in CalHeatScore.Score.values:
                    continue

                CalHeatScore.objects.update_or_create(
                    region=region,
                    date=base_date + timedelta(days=lead),
                    defaults={'score': score},
                )
