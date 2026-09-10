from datetime import timedelta

from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.models import Monitor


# Hours behind the just-closed hour to re-check for monitors that were skipped
# (no RAW PM2.5 entries yet) when that hour was first scored.
HEALTH_CHECK_LOOKBACK_HOURS = 3


@db_periodic_task(crontab(hour='*', minute='15'), priority=50)
def hourly_health_checks(hour=None):
    """
    Run QA/QC health checks for all PM2.5 monitors with multiple sensors.

    Runs at minute 15 (not right at the hour) because get_for_health_checks()
    only queues a monitor if it already has RAW PM2.5 entries for the target
    hour: VOZbox's upstream only publishes a batch ~65 min after each hour
    closes (see VOZBox.LAST_ACTIVE_LIMIT in camp/apps/monitors/vozbox/models.py),
    and import_realtime pulls it in on its next */10 min cycle -- landing in
    the DB around minute 10-11 of the following hour. Running at minute 1
    fired before that batch existed, so VOZbox never accumulated passing
    HealthCheck rows and was permanently excluded from filter_healthy()
    (e.g. the pm25/current/ API).

    hourly_region_summaries (camp/apps/summaries/tasks.py) reads these
    HealthCheck rows for the same hour and must stay scheduled after this.

    That margin is only a few minutes, so when no explicit hour is given we
    also look back over the previous few hours and score any monitor that
    has entries for that hour but no HealthCheck row yet -- a late upstream
    publish or a queue backlog then self-heals on the next run instead of
    leaving a permanent hole in the 24h window.
    """
    if hour is not None:
        for monitor in Monitor.objects.get_for_health_checks(hour):
            monitor_health_check(monitor.pk, hour)
        return

    this_hour = timezone.now().replace(minute=0, second=0, microsecond=0)
    last_hour = this_hour - timedelta(hours=1)

    for monitor in Monitor.objects.get_for_health_checks(last_hour):
        monitor_health_check(monitor.pk, last_hour)

    for offset in range(2, HEALTH_CHECK_LOOKBACK_HOURS + 1):
        lookback_hour = this_hour - timedelta(hours=offset)
        queryset = (Monitor.objects
            .get_for_health_checks(lookback_hour)
            .exclude(health_checks__hour=lookback_hour)
        )
        for monitor in queryset:
            monitor_health_check(monitor.pk, lookback_hour)


@db_task(priority=50)
def monitor_health_check(monitor_id, hour):
    monitor = Monitor.objects.get(pk=monitor_id)
    monitor.run_health_check(hour)
