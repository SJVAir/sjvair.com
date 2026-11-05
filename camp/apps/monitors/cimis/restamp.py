'''
Re-pull a CIMIS station's stored history and stamp it at the start of each
hour (CIMIS.parse_timestamp), replacing rows stamped the old way
(CIMIS.legacy_timestamp: end of the hour on the Pacific wall clock).
'''
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import sentry_sdk

from django.conf import settings
from django.db import transaction
from django.db.models import Min
from django.db.models.functions import ExtractHour, TruncDate

from camp.apps.monitors.cimis.api import CIMISAPI
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.models import LatestEntry
from camp.utils.datetime import localtime


@dataclass
class RestampResult:
    monitor_id: str
    start: date | None
    end: date
    labels: int
    deleted: int
    written: int
    # Rows in the delete window, by entry type.
    deleted_by_type: dict = field(default_factory=dict)
    # Malformed records skipped, as the live ingest skips them.
    skipped: int = 0


class ShortAnswer(Exception):
    '''The API returned no labels for a date that has stored rows.'''


def first_stored_date(monitor):
    '''The Pacific date of the station's earliest entry in any CIMIS table.'''
    earliest = [
        EntryModel.objects.filter(monitor_id=monitor.pk).aggregate(first=Min('timestamp'))['first']
        for EntryModel in CIMIS.ENTRY_CONFIG
    ]
    earliest = [timestamp for timestamp in earliest if timestamp is not None]
    if not earliest:
        return None
    return localtime(min(earliest)).date()


def fetch_records(monitor, start, end, api):
    '''Every record for this station from start to end, one API call per date.'''
    records = []
    day = start
    while day <= end:
        providers = api.get_hourly_data(
            station_numbers=[monitor.station_number],
            start_date=day,
            end_date=day,
            data_items=list(CIMIS.ENTRY_MAP.keys()),
        )
        for provider in providers:
            for record in provider.get('Records', []):
                if record.get('Station') == monitor.station_number:
                    records.append(record)
        day += timedelta(days=1)
    return records


def stored_dates(monitor, start, end):
    '''
    Dates in [start, end] with stored rows for this station. Only rows from
    01:00 Pacific up to midnight count: under both the old stamps (end of
    hour) and the new ones (start of hour, PST) those belong to that date's
    labels, while the midnight hour can be either day's.
    '''
    tz = settings.DEFAULT_TIMEZONE
    dates = set()
    for EntryModel in CIMIS.ENTRY_CONFIG:
        dates.update(
            EntryModel.objects
            .filter(monitor_id=monitor.pk)
            .annotate(day=TruncDate('timestamp', tzinfo=tz), hour=ExtractHour('timestamp', tzinfo=tz))
            .filter(day__gte=start, day__lte=end, hour__gte=1)
            .values_list('day', flat=True)
            .distinct()
        )
    return dates


def check_answer(monitor, start, end, records):
    labels = Counter(record.get('Date') for record in records)
    missing = sorted(day for day in stored_dates(monitor, start, end) if not labels[day.isoformat()])
    if missing:
        shown = ', '.join(day.isoformat() for day in missing[:10])
        more = f' (and {len(missing) - 10} more)' if len(missing) > 10 else ''
        raise ShortAnswer(
            f'CIMIS returned no labels for {len(missing)} date(s) with stored rows: {shown}{more}. '
            'Nothing written for this station.'
        )


def write_record(monitor, record):
    '''
    handle_payload, skipping a malformed record the way the live ingest does
    (process_cimis_data). Those errors are raised before any SQL, so catching
    them inside the transaction is safe; database errors still abort it.
    '''
    try:
        return len(monitor.handle_payload(record)), 0
    except (KeyError, ValueError, TypeError, AttributeError):
        sentry_sdk.capture_exception()
        return 0, 1


def delete_window(monitor, start, end):
    '''The old stamps of [start 0100, end 2400], inclusive.'''
    return (
        monitor.legacy_timestamp({'Date': start.isoformat(), 'Hour': '0100'}),
        monitor.legacy_timestamp({'Date': end.isoformat(), 'Hour': '2400'}),
    )


def rebuild_latest_entries(monitor):
    entry_types = [EntryModel.entry_type for EntryModel in CIMIS.ENTRY_CONFIG]
    LatestEntry.objects.filter(monitor_id=monitor.pk, entry_type__in=entry_types).delete()
    for EntryModel in CIMIS.ENTRY_CONFIG:
        newest = (
            EntryModel.objects
            .filter(monitor_id=monitor.pk, stage=EntryModel.Stage.RAW)
            .order_by('-timestamp')
            .first()
        )
        if newest is not None:
            monitor.update_latest_entry(newest)


def today():
    return localtime().date()


def restamp_station(monitor: CIMIS, dry_run: bool, api: CIMISAPI | None = None) -> RestampResult:
    '''
    Re-stamp everything from the station's first stored date through today
    (Pacific). Always through today: the window ends at the old stamp of
    (end, 2400), which is 00:00 of the next day, and in PST that is also the
    new stamp of the next day's 0100. With a past end, a next day already
    ingested the new way would lose that hour (deleted, not re-fetched).
    Through today, the next day's 0100 is still in the future.
    '''
    end = today()
    start = first_stored_date(monitor)
    if start is None or start > end:
        return RestampResult(monitor_id=monitor.pk, start=start, end=end, labels=0, deleted=0, written=0)

    # Fetch everything before touching the database: an API error leaves
    # the station as it was.
    api = api or CIMISAPI()
    records = fetch_records(monitor, start, end, api)
    check_answer(monitor, start, end, records)

    window_start, window_end = delete_window(monitor, start, end)
    querysets = {
        EntryModel: EntryModel.objects.filter(
            monitor_id=monitor.pk,
            timestamp__gte=window_start,
            timestamp__lte=window_end,
        )
        for EntryModel in CIMIS.ENTRY_CONFIG
    }

    if dry_run:
        deleted_by_type = {EntryModel.entry_type: qs.count() for EntryModel, qs in querysets.items()}
        return RestampResult(
            monitor_id=monitor.pk, start=start, end=end, labels=len(records),
            deleted=sum(deleted_by_type.values()), written=0, deleted_by_type=deleted_by_type,
        )

    deleted_by_type = {}
    written = skipped = 0
    with transaction.atomic():
        for EntryModel, qs in querysets.items():
            _total, per_model = qs.delete()
            deleted_by_type[EntryModel.entry_type] = per_model.get(EntryModel._meta.label, 0)

        for record in records:
            record_written, record_skipped = write_record(monitor, record)
            written += record_written
            skipped += record_skipped

        rebuild_latest_entries(monitor)

    return RestampResult(
        monitor_id=monitor.pk, start=start, end=end, labels=len(records),
        deleted=sum(deleted_by_type.values()), written=written, deleted_by_type=deleted_by_type, skipped=skipped,
    )
