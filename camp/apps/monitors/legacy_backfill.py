'''
Field mapping and pure construction logic for backfilling legacy `Entry` rows
(camp/apps/monitors/models.py) into the new `entries` app, RAW stage only.
See docs/superpowers/specs/2026-07-28-legacy-entries-backfill-design.md.
'''
from bisect import bisect_left
from datetime import timedelta

from django.db.models import Exists, OuterRef

from camp.apps.entries import models as entry_models

# A legacy row within this distance of an existing RAW row (same sensor) is
# treated as already covered. The two systems stamped the same reading
# differently (PurpleAir history import uses aligned timestamps, legacy used
# last_seen), so exact-match dedupe would interleave near-duplicates. Half of
# PurpleAir's 2-minute interval: any regular grid of existing rows is within
# 60s of every point it covers, while real gaps still get filled.
NEAR_DUPLICATE_WINDOW = timedelta(seconds=60)


def _bam_pm25_sentinel(legacy_entry):
    # Check the same coalesced value the mapping copies.
    value = legacy_entry.pm25_reported
    if value is None:
        value = legacy_entry.pm25
    return value == 99999


LEGACY_BACKFILL_MAP = {}


def _register(monitor_cls, mapping):
    LEGACY_BACKFILL_MAP[monitor_cls] = mapping


def _load_map():
    from camp.apps.monitors.purpleair.models import PurpleAir
    from camp.apps.monitors.airnow.models import AirNow
    from camp.apps.monitors.aqview.models import AQview
    from camp.apps.monitors.bam.models import BAM1022

    _register(PurpleAir, {
        entry_models.PM25: {'source': 'pm25_reported', 'target': 'value', 'per_sensor': True},
        entry_models.PM10: {'source': 'pm10', 'target': 'value', 'per_sensor': True},
        entry_models.PM100: {'source': 'pm100', 'target': 'value', 'per_sensor': True},
        entry_models.Particulates: {
            'source': [
                'particles_03um', 'particles_05um', 'particles_10um',
                'particles_25um', 'particles_50um', 'particles_100um',
            ],
            'per_sensor': True,
        },
        entry_models.Temperature: {'source': 'fahrenheit', 'target': 'fahrenheit', 'per_sensor': False},
        entry_models.Humidity: {'source': 'humidity', 'target': 'value', 'per_sensor': False},
        entry_models.Pressure: {'source': 'pressure', 'target': 'hpa', 'per_sensor': False},
    })

    _register(AirNow, {
        entry_models.PM25: {'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False},
        entry_models.PM100: {'source': 'pm100', 'target': 'value', 'per_sensor': False},
        entry_models.O3: {'source': 'ozone', 'target': 'value', 'per_sensor': False},
    })

    _register(AQview, {
        entry_models.PM25: {'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False},
    })

    _register(BAM1022, {
        entry_models.PM25: {
            'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False,
            'skip_if': _bam_pm25_sentinel,
        },
        entry_models.Temperature: {'source': 'celsius', 'target': 'celsius', 'per_sensor': False},
        entry_models.Humidity: {'source': 'humidity', 'target': 'value', 'per_sensor': False},
        entry_models.Pressure: {'source': 'pressure', 'target': 'mmhg', 'per_sensor': False},
    })


_load_map()


def build_raw_entry(monitor, legacy_entry, entry_model, mapping):
    '''
    Given a legacy Entry row and its mapping (one value of a LEGACY_BACKFILL_MAP
    entry), return an unsaved `entry_model` RAW instance, or None if the source
    data is missing or explicitly skipped.
    '''
    skip_if = mapping.get('skip_if')
    if skip_if and skip_if(legacy_entry):
        return None

    source = mapping['source']
    target = mapping.get('target')

    if isinstance(source, list):
        values = {}
        for field_name in source:
            value = getattr(legacy_entry, field_name)
            if value is None:
                return None
            values[field_name] = value
    else:
        if isinstance(source, tuple):
            value = None
            for field_name in source:
                value = getattr(legacy_entry, field_name)
                if value is not None:
                    break
        else:
            value = getattr(legacy_entry, source)

        if value is None:
            return None

        values = {target: value}

    if mapping.get('per_sensor'):
        sensor = legacy_entry.sensor
        allowed = monitor.ENTRY_CONFIG.get(entry_model, {}).get('sensors')
        if allowed is not None and sensor not in allowed:
            return None
    else:
        sensor = ''

    entry = entry_model(
        monitor=monitor,
        timestamp=legacy_entry.timestamp,
        sensor=sensor,
        position=legacy_entry.position,
        location=legacy_entry.location,
        stage=entry_model.Stage.RAW,
        processor='',
    )
    for field_name, value in values.items():
        setattr(entry, field_name, value)

    return entry


def eligible_monitor_classes():
    return list(LEGACY_BACKFILL_MAP.keys())


def chunk_start_for(cursor, range_start, chunk_days=7):
    return max(cursor - timedelta(days=chunk_days), range_start)


def chunk_end_for(cursor, range_end, chunk_days=7):
    return min(cursor + timedelta(days=chunk_days), range_end)


def _source_fields(mapping):
    source = mapping['source']
    if isinstance(source, list):
        return list(source)
    if isinstance(source, tuple):
        return list(source)
    return [source]


def find_missing_raw_entries(monitor, entry_model, mapping, chunk_start, chunk_end):
    '''
    Returns unsaved entry_model instances for legacy Entry rows in the window
    that have no RAW entry for the same sensor within NEAR_DUPLICATE_WINDOW.
    Safe to call repeatedly.
    '''
    from django.db.models import Q
    from camp.apps.monitors.models import Entry

    field_filter = Q()
    for field_name in _source_fields(mapping):
        field_filter |= Q(**{f'{field_name}__isnull': False})

    legacy_qs = Entry.objects.filter(
        field_filter,
        monitor=monitor,
        timestamp__gte=chunk_start,
        timestamp__lt=chunk_end,
    )

    existing = {}
    for timestamp, sensor in entry_model.objects.filter(
        monitor=monitor,
        stage=entry_model.Stage.RAW,
        timestamp__gte=chunk_start - NEAR_DUPLICATE_WINDOW,
        timestamp__lt=chunk_end + NEAR_DUPLICATE_WINDOW,
    ).values_list('timestamp', 'sensor'):
        existing.setdefault(sensor, []).append(timestamp)
    for timestamps in existing.values():
        timestamps.sort()

    seen = set()
    missing = []
    for legacy_entry in legacy_qs:
        entry = build_raw_entry(monitor, legacy_entry, entry_model, mapping)
        if entry is None:
            continue
        key = (entry.timestamp, entry.sensor)
        if key in seen or _has_near(existing.get(entry.sensor, ()), entry.timestamp):
            continue
        seen.add(key)
        missing.append(entry)

    return missing


def _has_near(sorted_timestamps, timestamp):
    i = bisect_left(sorted_timestamps, timestamp - NEAR_DUPLICATE_WINDOW)
    return i < len(sorted_timestamps) and sorted_timestamps[i] <= timestamp + NEAR_DUPLICATE_WINDOW


def monitors_with_legacy_data_in(chunk_start, chunk_end):
    '''
    Returns pks of monitors (of the eligible types) with at least one legacy
    Entry row in [chunk_start, chunk_end).
    '''
    from camp.apps.monitors.models import Entry

    entries_in_range = Entry.objects.filter(
        monitor=OuterRef('pk'),
        timestamp__gte=chunk_start,
        timestamp__lt=chunk_end,
    )

    monitor_ids = set()
    for monitor_cls in eligible_monitor_classes():
        ids = (monitor_cls.objects
            .annotate(has_legacy=Exists(entries_in_range))
            .filter(has_legacy=True)
            .values_list('pk', flat=True))
        monitor_ids.update(ids)
    return list(monitor_ids)


def pipeline_entry_models(monitor_class):
    '''
    EntryModels this monitor type both backfills from legacy data and runs
    through a processing pipeline (declares 'processors' in ENTRY_CONFIG),
    mapped to their terminal (final configured) stage.

    Scope note: `monitor_class` is only ever one of the LEGACY_BACKFILL_MAP-
    eligible types (PurpleAir, AirNow, AQview, BAM1022) -- the same four
    types this whole legacy-entries-backfill feature covers. AirGradient
    has a real ENTRY_CONFIG pipeline of its own but no legacy data, so it is
    intentionally absent from LEGACY_BACKFILL_MAP and therefore never
    reprocessed by this system, even though it could in principle have
    stuck/incomplete RAW entries from its own real-time-ingest pipeline.
    Extending reprocessing to AirGradient (or any other non-legacy monitor
    type) would be a scope expansion requiring its own design sign-off, not
    something this function's callers do.
    '''
    result = {}
    mapping = LEGACY_BACKFILL_MAP.get(monitor_class, {})
    for entry_model in mapping:
        config = monitor_class.ENTRY_CONFIG.get(entry_model, {})
        if 'processors' in config:
            result[entry_model] = config['allowed_stages'][-1]
    return result


def processable_stages(monitor_class, entry_model):
    '''
    Stages of entry_model that have at least one processor configured for
    this monitor type, i.e. stages an entry can be advanced from.
    '''
    return list(monitor_class.ENTRY_CONFIG.get(entry_model, {}).get('processors', {}))


def find_incomplete_pipelines(monitor, entry_model, chunk_start, chunk_end):
    '''
    Returns entry_model instances in the window that sit at a stage with a
    processor configured but have no derived entries yet, so the pipeline can
    continue from wherever it stopped -- e.g. PurpleAir PM2.5 migrated with
    CORRECTED and CLEANED but never CALIBRATED.

    Ordered oldest first, then by pipeline stage: PurpleAir's spike cleaning
    for an entry runs when the entry after it is corrected, and needs the
    CORRECTED entry before it to already exist.

    Some entries can never produce a next stage (PurpleAir sensor 'b' RAW
    rows, which correction folds into 'a'; calibrations missing an input),
    so they are picked up again on every pass. That costs a wasted attempt,
    nothing more.
    '''
    monitor_class = type(monitor)
    stage_order = monitor_class.ENTRY_CONFIG[entry_model]['allowed_stages']
    entries = entry_model.objects.filter(
        monitor=monitor,
        stage__in=processable_stages(monitor_class, entry_model),
        timestamp__gte=chunk_start,
        timestamp__lt=chunk_end,
        derived_entries__isnull=True,
    )
    return sorted(entries, key=lambda e: (e.timestamp, stage_order.index(e.stage), e.sensor))


def monitors_with_incomplete_pipelines_in(chunk_start, chunk_end):
    '''
    Returns pks of monitors (of the eligible types) with at least one entry
    in [chunk_start, chunk_end) that find_incomplete_pipelines would pick up,
    across any of that monitor type's pipeline-eligible entry models.

    Scope note: "eligible types" here means LEGACY_BACKFILL_MAP-eligible
    monitor types only (PurpleAir, AirNow, AQview, BAM1022) -- see the scope
    note on `pipeline_entry_models` above. This intentionally does NOT
    extend to AirGradient or any other monitor type outside that set, even
    though AirGradient has its own real processing pipeline: AirGradient
    never had legacy migration needs, so reprocessing its real-time-ingest
    pipeline is out of scope for this feature.
    '''
    monitor_ids = set()
    for monitor_cls in eligible_monitor_classes():
        models_map = pipeline_entry_models(monitor_cls)
        if not models_map:
            continue

        for entry_model in models_map:
            unprocessed_in_range = entry_model.objects.filter(
                monitor=OuterRef('pk'),
                stage__in=processable_stages(monitor_cls, entry_model),
                timestamp__gte=chunk_start,
                timestamp__lt=chunk_end,
                derived_entries__isnull=True,
            )
            ids = (monitor_cls.objects
                .annotate(has_incomplete=Exists(unprocessed_in_range))
                .filter(has_incomplete=True)
                .values_list('pk', flat=True))
            monitor_ids.update(ids)

    return list(monitor_ids)
