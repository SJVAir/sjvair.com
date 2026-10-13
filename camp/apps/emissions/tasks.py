from django.core.management import call_command

from django_huey import db_periodic_task, get_queue
from huey import crontab


# EPA refreshes the ICIS-Air bulk files weekly (Sunday, early UTC); a run is
# one ~70 MB download and a minute's work. Mondays at 12:00 UTC.
@db_periodic_task(crontab(day_of_week='1', hour='12', minute='0'), priority=20)
def import_icis_air():
    with get_queue('primary').lock_task('import-icis-air'):
        call_command('import_icis_air')


# CalGEM's WellSTAR layer is live; weekly keeps the map within a week of it.
# Sundays at 12:00 UTC.
@db_periodic_task(crontab(day_of_week='0', hour='12', minute='0'), priority=20)
def import_wells():
    with get_queue('primary').lock_task('import-wells'):
        call_command('import_wells')


# Carbon Mapper publishes new plumes continuously; monthly keeps the layer
# current without leaning on their API. The 4th at 11:00 UTC.
@db_periodic_task(crontab(day='4', hour='11', minute='0'), priority=20)
def import_carbon_mapper():
    with get_queue('primary').lock_task('import-carbon-mapper'):
        call_command('import_carbon_mapper')
