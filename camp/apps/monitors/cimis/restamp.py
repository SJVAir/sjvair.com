'''
Re-pull a CIMIS station's stored history and stamp it at the start of each
hour (CIMIS.parse_timestamp), replacing rows stamped the old way
(CIMIS.legacy_timestamp: end of the hour on the Pacific wall clock).
'''
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Min

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


def restamp_station(monitor: CIMIS, end: date, dry_run: bool, api: CIMISAPI | None = None) -> RestampResult:
    start = first_stored_date(monitor)
    if start is None or start > end:
        return RestampResult(monitor_id=monitor.pk, start=start, end=end, labels=0, deleted=0, written=0)

    # Fetch everything before touching the database: an API error leaves
    # the station as it was.
    api = api or CIMISAPI()
    records = fetch_records(monitor, start, end, api)

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
    written = 0
    with transaction.atomic():
        for EntryModel, qs in querysets.items():
            _total, per_model = qs.delete()
            deleted_by_type[EntryModel.entry_type] = per_model.get(EntryModel._meta.label, 0)

        for record in records:
            written += len(monitor.handle_payload(record))

        rebuild_latest_entries(monitor)

    return RestampResult(
        monitor_id=monitor.pk, start=start, end=end, labels=len(records),
        deleted=sum(deleted_by_type.values()), written=written, deleted_by_type=deleted_by_type,
    )
