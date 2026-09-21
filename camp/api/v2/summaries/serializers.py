from django.conf import settings

from resticus import serializers

from camp.api.v2.monitors.serializers import MonitorSerializer


def _timestamp(s):
    return s.timestamp.astimezone(settings.DEFAULT_TIMEZONE).isoformat()


class MonitorSummarySerializer(serializers.Serializer):
    fields = [
        ('timestamp', _timestamp),
        'entry_type',
        'resolution',
        'processor',
        'count',
        'expected_count',
        'minimum',
        'maximum',
        'mean',
        'stddev',
        'p25',
        'p75',
        'is_complete',
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
        'station_count',
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
