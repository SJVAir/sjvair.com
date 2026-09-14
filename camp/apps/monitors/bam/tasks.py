from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from django_huey import db_periodic_task
from huey import crontab

MIRROR_HOURS = 3


# Staging / local dev only. The task is only registered when the mirror
# is enabled, so production's scheduler never sees it.
if settings.BAM_MIRROR_ENABLED:
    @db_periodic_task(crontab(minute='20'), priority=50)
    def mirror_bam_entries():
        '''
        Pull the last few hours of BAM 1022 RAW entries from production
        and run them through the processing pipeline.
        '''
        end = timezone.now()
        start = end - timedelta(hours=MIRROR_HOURS)
        call_command('mirror_bam_entries', start=start.isoformat(), end=end.isoformat())
