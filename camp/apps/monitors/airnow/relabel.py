"""
Relabel the PM2.5, PM10, and ozone the import stored as RAW before it kept
RawConcentration: those values were AirNow's NowCast. backfill_airnow
replaced them for every site AirNow still returns, but its API leaves out
sites that have closed (e.g. Visalia - N. Church Street), so their old
values can't be re-fetched. They're kept, as the NowCast they are:
CALIBRATED under the NowCast processor, with the CLEANED entries derived
from them removed.

A series is relabeled only if it has no NowCast at all and stopped
reporting before the import was fixed: a site AirNow still returns was
backfilled, so its RAW is already RawConcentration.
"""

from datetime import datetime, timezone as dt_timezone

from django.db import transaction
from django.db.models import Count, Max, Min
from django.utils import timezone

from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.models import LatestEntry

# The import stored the NowCast as RAW until this release.
FIXED_AT = datetime(2026, 10, 21, tzinfo=dt_timezone.utc)


def find_series(before=FIXED_AT):
    '''Yield (monitor, processor, stats) for each series of NowCast-era RAW with no NowCast stored.'''
    for monitor in AirNow.objects.order_by('name'):
        for processor in AirNow.NOWCAST_PROCESSORS.values():
            EntryModel = processor.entry_model
            entries = EntryModel.objects.filter(monitor_id=monitor.pk, sensor='')
            if entries.filter(stage=EntryModel.Stage.CALIBRATED, processor=processor.name).exists():
                continue

            # A site still reporting after the fix was backfilled, so its RAW is already
            # RawConcentration even if AirNow never sends it a NowCast.
            raw = entries.filter(stage=EntryModel.Stage.RAW)
            if raw.filter(timestamp__gte=before).exists():
                continue

            stats = raw.aggregate(count=Count('pk'), first=Min('timestamp'), last=Max('timestamp'))
            if stats['count']:
                yield monitor, processor, stats


def relabel_series(monitor, processor, before=FIXED_AT):
    '''Move the series' RAW before `before` to the NowCast and drop what was derived from it. Returns counts.'''
    EntryModel = processor.entry_model
    Stage = EntryModel.Stage
    entries = EntryModel.objects.filter(monitor_id=monitor.pk, sensor='', timestamp__lt=before)
    raw = entries.filter(stage=Stage.RAW)
    derived = entries.filter(stage__in=[Stage.CORRECTED, Stage.CLEANED])

    with transaction.atomic():
        moved = set(raw.values_list('pk', flat=True)) | set(derived.values_list('pk', flat=True))
        stale = [latest.pk for latest in LatestEntry.objects.filter(monitor_id=monitor.pk, entry_type=EntryModel.entry_type)
                 if latest.entry_id in moved]
        LatestEntry.objects.filter(pk__in=stale).delete()

        removed = derived.delete()[0]
        relabeled = raw.update(stage=Stage.CALIBRATED, processor=processor.name, modified=timezone.now())

        # Point LatestEntry back at whatever is now newest in each series.
        series = EntryModel.objects.filter(monitor_id=monitor.pk, sensor='').values_list('stage', 'processor').distinct()
        for stage, name in series:
            newest = (EntryModel.objects
                .filter(monitor_id=monitor.pk, sensor='', stage=stage, processor=name)
                .order_by('-timestamp').first())
            monitor.update_latest_entry(newest)

    return {'relabeled': relabeled, 'removed': removed}


def relabel_nowcast(before=FIXED_AT, dry_run=False, log=None):
    log = log or (lambda msg: None)
    totals = {'series': 0, 'relabeled': 0, 'removed': 0}
    for monitor, processor, stats in list(find_series(before)):
        totals['series'] += 1
        summary = (f'{monitor.name} {processor.entry_model.__name__}: {stats["count"]} RAW, '
                   f'{stats["first"]:%Y-%m-%d %H:00} to {stats["last"]:%Y-%m-%d %H:00} UTC')
        if dry_run:
            totals['relabeled'] += stats['count']
            log(summary)
            continue

        counts = relabel_series(monitor, processor, before)
        for key, value in counts.items():
            totals[key] += value
        log(f'{summary}: {counts["relabeled"]} relabeled, {counts["removed"]} derived removed')
    return totals
