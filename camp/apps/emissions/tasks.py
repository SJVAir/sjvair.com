from django.core.management import call_command

from django_huey import db_periodic_task, get_queue
from huey import crontab


# EPA refreshes the ICIS-Air bulk files weekly (Sunday, early UTC); a run is
# one ~70 MB download and a minute's work. Mondays at 12:00 UTC.
@db_periodic_task(crontab(day_of_week='1', hour='12', minute='0'), priority=20)
def import_icis_air():
    with get_queue('primary').lock_task('import-icis-air'):
        call_command('import_icis_air')
