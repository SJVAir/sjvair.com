from django.core.management import call_command

from django_huey import db_periodic_task, get_queue
from huey import crontab


# EPA refreshes the ICIS-Air bulk files weekly; SJVAPCD's feed into them runs
# a year or more behind, so monthly is plenty. The 2nd at 11:00 UTC.
@db_periodic_task(crontab(day='2', hour='11', minute='0'), priority=20)
def import_icis_air():
    with get_queue('primary').lock_task('import-icis-air'):
        call_command('import_icis_air')
