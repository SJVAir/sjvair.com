from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings

from resticus import serializers

from camp.api.v2.monitors.serializers import MonitorSerializer
from camp.apps.summaries.schedule import row_is_final

# The instant `is_final` is judged at. The summary endpoints bind it once per
# request (serializing_at), so every row and the cache rule agree; unbound,
# rows use the current time.
_serialize_now = ContextVar('summary_serialize_now', default=None)


@contextmanager
def serializing_at(now):
    token = _serialize_now.set(now)
    try:
        yield
    finally:
        _serialize_now.reset(token)


def _timestamp(s):
    return s.timestamp.astimezone(settings.DEFAULT_TIMEZONE).isoformat()


def _is_final(s):
    return row_is_final(s.resolution, s.timestamp, s.entry_type, now=_serialize_now.get())


class MonitorSummarySerializer(serializers.Serializer):
    fields = [
        ('timestamp', _timestamp),
        'entry_type',
        'resolution',
        'processor',
        'count',
        ('sum', lambda s: s.sum_value),
        'expected_count',
        'minimum',
        'maximum',
        'mean',
        'stddev',
        'p25',
        'p75',
        'max_1h',
        'max_8h',
        'mean_24h',
        'is_complete',
        ('is_final', _is_final),
    ]


class BulkMonitorSummaryGroupSerializer(MonitorSerializer):
    """A monitor (same shape as MonitorSerializer) with a nested `summaries`
    list - the summary rows for that monitor within the requested page.

    The endpoint paginates by summary row (not by monitor) to keep response
    size bounded regardless of how many monitors/rows-per-monitor a request
    matches; see BulkMonitorSummaryList's docstring for what that means for
    a monitor whose rows span a page boundary.
    """
    include = [
        # monitor.summary_rows is stashed by BulkMonitorSummaryList.serialize();
        # not `monitor.summaries` - that name is taken by the FK's reverse
        # related manager (Monitor.summaries), which would run an unscoped,
        # unbounded query instead of using the current page's filtered rows.
        ('summaries', lambda monitor: MonitorSummarySerializer(monitor.summary_rows).serialize()),
    ]


class RegionSummarySerializer(serializers.Serializer):
    fields = [
        ('timestamp', _timestamp),
        'entry_type',
        'resolution',
        'count',
        'expected_count',
        'minimum',
        'maximum',
        'mean',
        'stddev',
        'p25',
        'p75',
        'max_1h',
        'max_8h',
        'mean_24h',
        'station_count',
        ('is_final', _is_final),
    ]


class BulkRegionSummaryGroupSerializer(serializers.Serializer):
    """A region (id/name/slug/type, as in RegionSerializer but without the
    boundary geometry, which would otherwise be repeated on every page the
    region spans) with a nested `summaries` list - the summary rows for that
    region within the requested page. Mirrors BulkMonitorSummaryGroupSerializer's
    monitor/summaries relationship."""
    fields = (
        ('id', lambda r: r.sqid),
        'name',
        'slug',
        'type',
    )
    include = [
        ('summaries', lambda region: RegionSummarySerializer(region.summary_rows).serialize()),
    ]
